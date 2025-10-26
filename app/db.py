from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
engine = create_engine('sqlite:///./data.db', echo=False, future=True)
class Base(DeclarativeBase): pass
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)

def init_db():
    from . import models
    Base.metadata.create_all(bind=engine)
