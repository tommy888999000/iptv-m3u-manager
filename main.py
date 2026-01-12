from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select
import asyncio
import os
from datetime import datetime

from database import engine, create_engine, sqlite_url
from models import SQLModel, Subscription, Channel, OutputSource
from routers import subscriptions, outputs, tools

app = FastAPI(title="IPTV M3U Manager")

# Serve static files
if not os.path.exists("./static"):
    os.makedirs("./static", exist_ok=True)
app.mount("/static", StaticFiles(directory="./static"), name="static")

# Include Routers
app.include_router(subscriptions.router)
app.include_router(outputs.router)
app.include_router(tools.router)

from sqlalchemy import text

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def migrate_db():
    with Session(engine) as session:
        # Check and add columns for Subscription
        try:
            session.exec(text("SELECT last_update_status FROM subscription LIMIT 1"))
        except:
            print("Migrating Subscription: adding last_update_status")
            session.exec(text("ALTER TABLE subscription ADD COLUMN last_update_status VARCHAR"))
            session.commit()
            
        try:
            session.exec(text("SELECT auto_update_minutes FROM subscription LIMIT 1"))
        except:
            print("Migrating Subscription: adding auto_update_minutes")
            session.exec(text("ALTER TABLE subscription ADD COLUMN auto_update_minutes INTEGER DEFAULT 0"))
            session.commit()

        try:
            session.exec(text("SELECT is_enabled FROM subscription LIMIT 1"))
        except:
            print("Migrating Subscription: adding is_enabled")
            session.exec(text("ALTER TABLE subscription ADD COLUMN is_enabled BOOLEAN DEFAULT 1"))
            session.commit()
        
        try:
            session.exec(text("SELECT tvg_id FROM channel LIMIT 1"))
        except:
            print("Migrating Channel: adding tvg_id")
            session.exec(text("ALTER TABLE channel ADD COLUMN tvg_id VARCHAR"))
            session.commit()

        try:
            session.exec(text("SELECT epg_url FROM outputsource LIMIT 1"))
        except:
            print("Migrating OutputSource: adding epg_url")
            session.exec(text("ALTER TABLE outputsource ADD COLUMN epg_url VARCHAR"))
            session.commit()

        try:
            session.exec(text("SELECT include_source_suffix FROM outputsource LIMIT 1"))
        except:
            print("Migrating OutputSource: adding include_source_suffix")
            session.exec(text("ALTER TABLE outputsource ADD COLUMN include_source_suffix BOOLEAN DEFAULT 1"))
            session.commit()

        # Check and add columns for OutputSource
        try:
            session.exec(text("SELECT last_updated FROM outputsource LIMIT 1"))
        except:
            print("Migrating OutputSource: adding last_updated and last_update_status")
            session.exec(text("ALTER TABLE outputsource ADD COLUMN last_updated DATETIME"))
            session.exec(text("ALTER TABLE outputsource ADD COLUMN last_update_status VARCHAR"))
            session.commit()
        
        try:
            session.exec(text("SELECT last_request_time FROM outputsource LIMIT 1"))
        except:
             print("Migrating OutputSource: adding last_request_time")
             session.exec(text("ALTER TABLE outputsource ADD COLUMN last_request_time DATETIME"))
             session.commit()

async def auto_update_task():
    """Background task to check and update subscriptions."""
    while True:
        try:
            with Session(engine) as session:
                subs = session.exec(select(Subscription)).all()
                for sub in subs:
                    if sub.auto_update_minutes > 0:
                        now = datetime.utcnow()
                        # If never updated, treat as very old
                        last = sub.last_updated or datetime.min
                        elapsed_mins = (now - last).total_seconds() / 60
                        
                        if elapsed_mins >= sub.auto_update_minutes:
                            print(f"[AutoUpdate] Triggering update for sub {sub.id} ({sub.name}). Elapsed: {elapsed_mins:.1f}m")
                            try:
                                # Import here to avoid circular dependency if possible, or move helper to service
                                from routers.subscriptions import process_subscription_refresh
                                count = await process_subscription_refresh(session, sub)
                                print(f"[AutoUpdate] Sub {sub.id} updated. {count} channels.")
                            except Exception as e:
                                print(f"[AutoUpdate] Failed for sub {sub.id}: {e}")
                                sub.last_update_status = f"AutoUpdate Error: {str(e)}"
                                session.add(sub)
                                session.commit()
        except Exception as outer_e:
            print(f"[AutoUpdate] Loop error: {outer_e}")
            
        await asyncio.sleep(60) # Check every minute

@app.on_event("startup")
def on_startup():
    create_db_and_tables()
    migrate_db()
    asyncio.create_task(auto_update_task())

@app.get("/")
def read_index():
    with open("./static/index.html", encoding="utf-8") as f:
        return Response(content=f.read(), media_type="text/html")
