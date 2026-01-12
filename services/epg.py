import os
import gzip
import io
import asyncio
import aiohttp
import xml.etree.ElementTree as ET
from hashlib import md5
from datetime import datetime
from typing import Dict, Any

EPG_CACHE_DIR = "./epg_cache"
if not os.path.exists(EPG_CACHE_DIR):
    os.makedirs(EPG_CACHE_DIR, exist_ok=True)

async def fetch_epg_cached(url: str, refresh: bool = False) -> str:
    """Download EPG, handle gzip, and cache locally for 1 hour."""
    if not url:
        return None
        
    url_hash = md5(url.encode()).hexdigest()
    cache_path = os.path.join(EPG_CACHE_DIR, f"{url_hash}.xml")
    
    # Check cache (1 hour expiry) unless refresh is true
    if not refresh and os.path.exists(cache_path):
        mtime = os.path.getmtime(cache_path)
        if (datetime.now().timestamp() - mtime) < 3600:
            return cache_path

    print(f"Downloading EPG: {url}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as response:
                if response.status != 200:
                    return None
                content = await response.read()
                
                # Decompress if needed
                if url.endswith(".gz") or content[:2] == b'\x1f\x8b':
                    try:
                        with gzip.GzipFile(fileobj=io.BytesIO(content)) as gz:
                            xml_content = gz.read()
                    except:
                        xml_content = content
                else:
                    xml_content = content
                    
                with open(cache_path, "wb") as f:
                    f.write(xml_content)
        return cache_path
    except Exception as e:
        print(f"Failed to fetch EPG {url}: {e}")
        return None

def find_current_program(xml_path: str, channel_id: str, channel_name: str):
    """Parse XML to find current program for a channel."""
    if not os.path.exists(xml_path):
        return None
    
    # We first need to map names to IDs if we only have a name
    name_to_id = {}
    target_ids = {channel_id} if channel_id else set()
    
    now_str = datetime.now().strftime("%Y%m%d%H%M%S")
    current = None
    
    try:
        context = ET.iterparse(xml_path, events=("start", "end"))
        _, root = next(context)
        
        for event, elem in context:
            if event == "end":
                if elem.tag == "channel":
                    cid = elem.get("id")
                    dn = elem.find("display-name")
                    if cid and dn is not None and dn.text:
                        name_to_id[dn.text.strip()] = cid
                
                elif elem.tag == "programme":
                    chan = elem.get("channel")
                    
                    possible_ids = target_ids.copy()
                    if channel_name and channel_name.strip() in name_to_id:
                        possible_ids.add(name_to_id[channel_name.strip()])
                    if channel_id and channel_id.strip() in name_to_id:
                        possible_ids.add(name_to_id[channel_id.strip()])
                    
                    if chan in possible_ids:
                        start = elem.get("start", "")[:14]
                        stop = elem.get("stop", "")[:14]
                        
                        if start <= now_str <= stop:
                            title_node = elem.find("title")
                            current = title_node.text if title_node is not None else "Unknown"
                    
                    root.clear()
        return current
    except Exception as e:
        print(f"EPG Parse error: {e}")
        return None

class EPGManager:
    _cache: Dict[str, Dict[str, Any]] = {}
    _lock = asyncio.Lock()
    
    @classmethod
    async def get_program(cls, epg_url: str, channel_id: str, channel_name: str) -> str:
        if not epg_url: return "No EPG URL"
        
        url_hash = md5(epg_url.encode()).hexdigest()
        
        async with cls._lock:
            # 1. Check Memory Cache
            now_ts = datetime.now().timestamp()
            if url_hash in cls._cache:
                cache_entry = cls._cache[url_hash]
                if (now_ts - cache_entry["timestamp"]) < 3600:
                    return cls._lookup_in_memory(cache_entry, channel_id, channel_name)
                else:
                    del cls._cache[url_hash]
            
            # 2. Not in memory, check/fetch file
            xml_path = await fetch_epg_cached(epg_url)
            if not xml_path or not os.path.exists(xml_path):
                return "Fetch Failed"
                
            # 3. Parse and Index into Memory
            try:
                parsed_data = cls._parse_epg_file(xml_path)
                cls._cache[url_hash] = {
                    "timestamp": now_ts,
                    "programs": parsed_data["programs"],
                    "name_map": parsed_data["name_map"]
                }
                return cls._lookup_in_memory(cls._cache[url_hash], channel_id, channel_name)
            except Exception as e:
                print(f"EPG Indexing Error: {e}")
                return "Parse Error"

    @staticmethod
    def _lookup_in_memory(cache_entry, channel_id, channel_name):
        programs = cache_entry["programs"]
        name_map = cache_entry["name_map"]
        
        target_ids = set()
        if channel_id: target_ids.add(channel_id)
        if channel_name:
            target_ids.add(channel_name)
            if channel_name in name_map: target_ids.add(name_map[channel_name])
        if channel_id and channel_id in name_map: target_ids.add(name_map[channel_id])
            
        now_str = datetime.now().strftime("%Y%m%d%H%M%S")
        for tid in target_ids:
            if tid in programs:
                for start, stop, title in programs[tid]:
                    if start <= now_str <= stop: return title
        return "No Program Info"

    @staticmethod
    def _parse_epg_file(xml_path):
        programs = {}
        name_map = {}
        context = ET.iterparse(xml_path, events=("start", "end"))
        _, root = next(context)
        for event, elem in context:
            if event == "end":
                if elem.tag == "channel":
                    cid = elem.get("id")
                    dn = elem.find("display-name")
                    if cid and dn is not None and dn.text:
                        name_map[dn.text.strip()] = cid
                elif elem.tag == "programme":
                    chan = elem.get("channel")
                    start = elem.get("start", "")[:14]
                    stop = elem.get("stop", "")[:14]
                    title_elem = elem.find("title")
                    title = title_elem.text if title_elem is not None else "Unknown"
                    if chan and start and stop:
                        if chan not in programs: programs[chan] = []
                        programs[chan].append((start, stop, title))
                    root.clear()
        return {"programs": programs, "name_map": name_map}
