from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from configs.settings import settings
import os

db_path = settings.DATABASE_URL.replace('sqlite:///', '')
if not db_path.startswith(':'): # Not memory db
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

engine = create_engine(
    settings.DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

from models.base import Base

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
