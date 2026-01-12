import re
import aiohttp
import json
import os
import subprocess
import hashlib
import glob
from models import Channel

class M3UParser:
    @staticmethod
    def parse(content: str):
        channels = []
        lines = content.splitlines()
        current_channel = None
        
        print(f"Parsing content, total lines: {len(lines)}")
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#EXTINF:"):
                # Extract name: find the last comma
                name = "Unknown"
                if "," in line:
                    name = line.rsplit(",", 1)[1].strip()
                
                # Extract attributes using a more robust regex
                # This matches key="value" pattern
                attrs = dict(re.findall(r'(\w+-\w+|\w+)="([^"]*)"', line))
                
                current_channel = {
                    "name": name,
                    "group": attrs.get("group-title", "Default"),
                    "logo": attrs.get("tvg-logo", ""),
                    "tvg_id": attrs.get("tvg-id", "")
                }
            elif any(line.startswith(p) for p in ["http", "rtmp", "p3p", "rtp", "udp", "mms"]):
                if current_channel:
                    current_channel["url"] = line
                    channels.append(current_channel)
                    current_channel = None
                else:
                    # Generic URL found without EXTINF
                    channels.append({
                        "name": line.split("/")[-1],
                        "url": line,
                        "group": "Default",
                        "logo": "",
                        "tvg_id": ""
                    })
        
        print(f"Parsed {len(channels)} channels.")
        return channels

class IPTVFetcher:
    @staticmethod
    def process_git_repo(url: str):
        repo_cache_base = "repo_cache"
        if not os.path.exists(repo_cache_base):
            os.makedirs(repo_cache_base)
            
        # Create a unique dir name based on URL hash
        url_hash = hashlib.md5(url.encode()).hexdigest()
        repo_dir = os.path.join(repo_cache_base, url_hash)
        
        print(f"Processing Git Repo: {url} -> {repo_dir}")
        
        try:
            if os.path.exists(os.path.join(repo_dir, ".git")):
                # Already exists, pull
                print("Repo exists, pulling updates...")
                subprocess.check_call(["git", "-C", repo_dir, "pull"], timeout=60)
            else:
                # Clone
                print("Cloning repo...")
                subprocess.check_call(["git", "clone", url, repo_dir], timeout=120)
        except subprocess.CalledProcessError as e:
            print(f"Git command failed: {e}")
            raise Exception(f"Git operation failed: {e}")
        except Exception as ex:
             print(f"Git error: {ex}")
             raise Exception(f"Git error: {ex}")

        # Scan for .m3u or .m3u8 files
        m3u_files = []
        for root, dirs, files in os.walk(repo_dir):
            # Skip hidden dirs like .git
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for file in files:
                if file.lower().endswith(('.m3u', '.m3u8')):
                    m3u_files.append(os.path.join(root, file))
        
        print(f"Found {len(m3u_files)} M3U files in repo.")
        
        all_channels = []
        for fpath in m3u_files:
            try:
                print(f"Reading file: {fpath}")
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    channels = M3UParser.parse(content)
                    # Add source file info to group or name? 
                    # Let's append filename to group to distinguish sources?
                    # Or just return them. The user probably wants them combined.
                    # M3UParser logic doesn't preserve source file info unless we modify it.
                    # Let's keep it simple for now.
                    all_channels.extend(channels)
            except Exception as e:
                print(f"Error reading {fpath}: {e}")
        
        return all_channels

    @staticmethod
    async def fetch_subscription(url: str, ua: str, headers_json: str):
        url = url.strip()
        
        # Git Detection
        if url.endswith(".git") or ("github.com" in url and ".git" in url):
             # Run in thread pool to avoid blocking async loop since subprocess is blocking-ish
             # Actually subprocess is blocking, but we can wrap it?
             # For simplicity in this context, we can call it directly, 
             # but strictly we should run_in_executor.
             import asyncio
             loop = asyncio.get_event_loop()
             return await loop.run_in_executor(None, IPTVFetcher.process_git_repo, url)

        # Use TiviMate UA defaults
        if not ua or ua == "Mozilla/5.0":
            ua = "TiviMate/4.7.0 (Linux; Android 11)"
            
        print(f"--- Starting fetch for URL: [{url}] with UA: [{ua}] ---")
        try:
            headers = json.loads(headers_json)
        except:
            headers = {}
        headers["User-Agent"] = ua
        
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            try:
                async with session.get(url, headers=headers, timeout=30) as response:
                    print(f"Fetch response status: {response.status} for {url}")
                    if response.status == 200:
                        content = await response.text(errors='ignore')
                        # Check if we got HTML instead of M3U
                        if "<html" in content.lower() and "#EXTM3U" not in content:
                            print("Warning: Received HTML instead of M3U. Check UA or URL.")
                            raise Exception("Server returned a webpage instead of M3U. Try changing UA or contact support.")
                        return M3UParser.parse(content)
                    else:
                        raise Exception(f"HTTP {response.status}")
            except Exception as e:
                import traceback
                print(f"Fetch error details for {url}:")
                traceback.print_exc()
                raise e
