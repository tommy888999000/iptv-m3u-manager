from sqlmodel import create_engine, Session
from sqlalchemy.orm import sessionmaker

sqlite_url = "sqlite:///./database.db"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

def get_session():
    with Session(engine) as session:
        yield session
