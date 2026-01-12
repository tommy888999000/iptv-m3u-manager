from fastapi import APIRouter, HTTPException, Depends, Response
from sqlmodel import Session, select
from typing import List, Dict, Any
import json
from datetime import datetime
import re

from models import OutputSource, Subscription, Channel
from database import get_session
from services.generator import M3UGenerator
from routers.subscriptions import process_subscription_refresh

router = APIRouter(tags=["outputs"])

@router.post("/outputs/", response_model=OutputSource)
def create_output(out: OutputSource, session: Session = Depends(get_session)):
    session.add(out)
    session.commit()
    session.refresh(out)
    return out

@router.get("/outputs/", response_model=List[OutputSource])
def list_outputs(session: Session = Depends(get_session)):
    return session.exec(select(OutputSource)).all()

@router.delete("/outputs/{output_id}")
def delete_output(output_id: int, session: Session = Depends(get_session)):
    out = session.get(OutputSource, output_id)
    if not out:
        raise HTTPException(status_code=404, detail="Output not found")
    session.delete(out)
    session.commit()
    return {"message": "Deleted successfully"}

@router.put("/outputs/{output_id}", response_model=OutputSource)
def update_output(output_id: int, output_data: OutputSource, session: Session = Depends(get_session)):
    output = session.get(OutputSource, output_id)
    if not output:
        raise HTTPException(status_code=404, detail="Output not found")
    
    # Check slug uniqueness only if it's being changed
    if output_data.slug != output.slug:
        existing = session.exec(select(OutputSource).where(OutputSource.slug == output_data.slug)).first()
        if existing:
            raise HTTPException(status_code=400, detail="Slug already exists")

    output.name = output_data.name
    output.slug = output_data.slug
    output.filter_regex = output_data.filter_regex
    output.keywords = output_data.keywords
    output.subscription_ids = output_data.subscription_ids
    output.epg_url = output_data.epg_url
    output.include_source_suffix = output_data.include_source_suffix
    
    session.add(output)
    session.commit()
    session.refresh(output)
    return output

@router.post("/outputs/preview")
def preview_output(data: dict, session: Session = Depends(get_session)):
    # data keys: subscription_ids, keywords (list of {value, group}), filter_regex
    sub_ids = data.get("subscription_ids", [])
    raw_keywords = data.get("keywords", [])
    regex = data.get("filter_regex", ".*")
    
    # Normalize keywords to list of dicts
    keywords = []
    for k in raw_keywords:
        if isinstance(k, str):
            keywords.append({"value": k, "group": ""})
        elif isinstance(k, dict):
            keywords.append(k)

    # Only fetch channels from enabled subscriptions
    enabled_subs = session.exec(select(Subscription.id).where(Subscription.is_enabled == True)).all()
    active_sub_ids = [sid for sid in sub_ids if sid in enabled_subs] if sub_ids else enabled_subs

    if active_sub_ids:
        channels = session.exec(select(Channel).where(Channel.subscription_id.in_(active_sub_ids))).all()
    else:
        channels = []
        
    # Fetch Sub Map
    subs = session.exec(select(Subscription)).all()
    sub_map = {s.id: s.name or s.url for s in subs}

    # Apply global regex filter first if any
    if regex and regex != ".*":
        try:
            pattern = re.compile(regex, re.IGNORECASE)
            channels = [c for c in channels if pattern.search(c.name)]
        except:
            pass

    results = {}
    if not keywords:
        # Propagate before dump
        channels = M3UGenerator.propagate_logos(channels)
        
        # If no keywords, just group by "All"
        results["All"] = [
            {**c.model_dump(), "source": sub_map.get(c.subscription_id, "Unknown")} 
            for c in channels 
        ]
    else:
        # Apply propagation to the source list 'channels' first!
        channels = M3UGenerator.propagate_logos(channels)
        
        # Strategy: We reuse the generator logic per keyword to emulate the result
        for k_obj in keywords:
            k_val = k_obj.get("value", "")
            k_group = k_obj.get("group", "")
            if not k_val: continue
            
            # Filter specifically for this keyword to show what IT matches
            matches = M3UGenerator.filter_channels(channels, None, [k_obj])
            
            display_key = f"{k_val} → {k_group}" if k_group else k_val
            
            results[display_key] = [
                {**c.model_dump(), "source": sub_map.get(c.subscription_id, "Unknown")} 
                for c in matches 
            ]
            
    return results

@router.post("/outputs/{output_id}/refresh")
async def refresh_output(output_id: int, session: Session = Depends(get_session)):
    out = session.get(OutputSource, output_id)
    if not out:
        raise HTTPException(status_code=404, detail="Output not found")
    
    try:
        sub_ids = json.loads(out.subscription_ids)
    except:
        sub_ids = []
        
    results = []
    for sub_id in sub_ids:
        try:
            sub = session.get(Subscription, sub_id)
            if sub:
               await process_subscription_refresh(session, sub)
               results.append(f"Sub {sub_id}: Success")
        except Exception as e:
            sub = session.get(Subscription, sub_id)
            if sub:
                sub.last_update_status = f"Error: {str(e)}"
                session.add(sub)
            results.append(f"Sub {sub_id}: Failed")
    
    out.last_updated = datetime.utcnow()
    out.last_update_status = "Checked linked subs"
    session.add(out)
    session.commit()
    return {"message": "Refresh complete", "details": results}

@router.get("/m3u/{slug}")
async def get_m3u_output(slug: str, session: Session = Depends(get_session)):
    out = session.exec(select(OutputSource).where(OutputSource.slug == slug)).first()
    if not out:
        raise HTTPException(status_code=404, detail="Output source not found")
    
    # Track Request Time
    out.last_request_time = datetime.utcnow()
    session.add(out)
    session.commit()
    
    try:
        sub_ids = json.loads(out.subscription_ids)
    except:
        sub_ids = []

    # Auto-refresh logic (Simple sequential)
    for sub_id in sub_ids:
         try:
            sub = session.get(Subscription, sub_id)
            if sub:
               await process_subscription_refresh(session, sub)
               sub.last_update_status = "Success (Client Trigger)"
               session.add(sub)
               session.commit()
         except Exception as e:
             # print(f"Auto-refresh failed for sub {sub_id}: {e}")
             pass
    
    # Re-fetch channels after update
    enabled_subs = session.exec(select(Subscription.id).where(Subscription.is_enabled == True)).all()
    active_sub_ids = [sid for sid in sub_ids if sid in enabled_subs] if sub_ids else enabled_subs

    if active_sub_ids:
        channels = session.exec(select(Channel).where(Channel.subscription_id.in_(active_sub_ids))).all()
    else:
        channels = []

    subs = session.exec(select(Subscription)).all()
    sub_map = {s.id: s.name or s.url for s in subs}

    try:
        raw_keywords = json.loads(out.keywords)
        keywords = []
        for k in raw_keywords:
            if isinstance(k, str):
                keywords.append({"value": k, "group": ""})
            elif isinstance(k, dict):
                keywords.append(k)
    except:
        keywords = []
        
    filtered = M3UGenerator.filter_channels(channels, out.filter_regex, keywords)
    m3u_content = M3UGenerator.generate_m3u(filtered, sub_map, out.epg_url, out.include_source_suffix)
    return Response(content=m3u_content, media_type="application/x-mpegurl; charset=utf-8")
