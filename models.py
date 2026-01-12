from datetime import datetime
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship

class Subscription(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    url: str
    user_agent: str = Field(default="Mozilla/5.0")
    headers: str = Field(default="{}")  # JSON string
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    last_update_status: Optional[str] = None  # "Success" or error message
    auto_update_minutes: int = Field(default=0) # 0 = disabled
    is_enabled: bool = Field(default=True)
    is_enabled: bool = Field(default=True)

    channels: List["Channel"] = Relationship(back_populates="subscription")

class Channel(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    url: str
    group: Optional[str] = None
    logo: Optional[str] = None
    tvg_id: Optional[str] = Field(default=None)
    subscription_id: int = Field(foreign_key="subscription.id")
    
    subscription: Subscription = Relationship(back_populates="channels")

class OutputSource(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    slug: str = Field(unique=True, index=True) # URL identifier
    epg_url: Optional[str] = Field(default=None)
    include_source_suffix: bool = Field(default=True)
    filter_regex: str = Field(default=".*")
    keywords: str = Field(default="[]") # JSON list of strings
    subscription_ids: str = Field(default="[]") # JSON list of IDs
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    last_update_status: Optional[str] = None
    last_request_time: Optional[datetime] = None
