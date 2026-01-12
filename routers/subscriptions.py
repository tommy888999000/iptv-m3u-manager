from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from typing import List
from models import Subscription, Channel
from database import get_session
from services.fetcher import IPTVFetcher
from datetime import datetime

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

@router.post("/", response_model=Subscription)
def create_subscription(sub: Subscription, session: Session = Depends(get_session)):
    sub.url = sub.url.strip()
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return sub

@router.get("/", response_model=List[Subscription])
def list_subscriptions(session: Session = Depends(get_session)):
    return session.exec(select(Subscription)).all()

@router.delete("/{sub_id}")
def delete_subscription(sub_id: int, session: Session = Depends(get_session)):
    sub = session.get(Subscription, sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    
    # Delete associated channels first
    channels = session.exec(select(Channel).where(Channel.subscription_id == sub_id)).all()
    for c in channels:
        session.delete(c)
        
    session.delete(sub)
    session.commit()
    return {"message": "Deleted successfully"}

@router.put("/{sub_id}", response_model=Subscription)
def update_subscription(sub_id: int, updated: Subscription, session: Session = Depends(get_session)):
    db_sub = session.get(Subscription, sub_id)
    if not db_sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    db_sub.name = updated.name
    db_sub.url = updated.url.strip()
    db_sub.user_agent = updated.user_agent
    db_sub.headers = updated.headers
    db_sub.auto_update_minutes = updated.auto_update_minutes
    db_sub.is_enabled = updated.is_enabled
    session.add(db_sub)
    session.commit()
    session.refresh(db_sub)
    return db_sub

@router.get("/{sub_id}/channels", response_model=List[Channel])
def get_subscription_channels(sub_id: int, session: Session = Depends(get_session)):
    sub = session.get(Subscription, sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    channels = session.exec(select(Channel).where(Channel.subscription_id == sub_id)).all()
    return channels

async def process_subscription_refresh(session: Session, sub: Subscription) -> int:
    """Helper to refresh a subscription inside an existing session/transaction context."""
    # Clear old channels
    old_channels = session.exec(select(Channel).where(Channel.subscription_id == sub.id)).all()
    for c in old_channels:
        session.delete(c)
    
    # Fetch new
    channels_data = await IPTVFetcher.fetch_subscription(sub.url, sub.user_agent, sub.headers)
    for item in channels_data:
        channel = Channel(**item, subscription_id=sub.id)
        session.add(channel)
    
    sub.last_updated = datetime.utcnow()
    sub.last_update_status = "Success"
    session.add(sub)
    session.commit()
    return len(channels_data)

@router.post("/{sub_id}/refresh")
async def refresh_subscription(sub_id: int, session: Session = Depends(get_session)):
    sub = session.get(Subscription, sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    
    try:
        count = await process_subscription_refresh(session, sub)
        return {"message": f"Fetched {count} channels"}
    except Exception as e:
        sub = session.get(Subscription, sub_id) # reload if stale
        if sub:
            sub.last_update_status = f"Error: {str(e)}"
            session.add(sub)
            session.commit()
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
