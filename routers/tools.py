from fastapi import APIRouter
import asyncio
import aiohttp
from sqlmodel import SQLModel

from services.connectivity import check_url
from services.epg import EPGManager, fetch_epg_cached, md5

router = APIRouter(tags=["tools"])

class CheckRequest(SQLModel):
    urls: list[str]

@router.post("/check-connectivity")
async def check_connectivity(req: CheckRequest):
    async with aiohttp.ClientSession() as session:
        tasks = [check_url(u, session) for u in req.urls]
        results = await asyncio.gather(*tasks)
        return results

@router.get("/api/epg/current")
async def get_epg_status(epg_url: str, tvg_id: str = None, tvg_name: str = None, refresh: bool = False):
    if not epg_url:
        return {"program": "No EPG URL"}
    
    # If refresh is requested, clearing the memory cache for this URL would be ideal
    if refresh:
        url_hash = md5(epg_url.encode()).hexdigest()
        async with EPGManager._lock:
            if url_hash in EPGManager._cache:
                del EPGManager._cache[url_hash]
        # Also refresh disk cache
        await fetch_epg_cached(epg_url, refresh=True)

    program = await EPGManager.get_program(epg_url, tvg_id, tvg_name)
    return {"program": program}
