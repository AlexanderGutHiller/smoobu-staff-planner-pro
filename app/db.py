
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# Verwende persistentes Volume auf Fly.io, falls vorhanden, sonst lokales Verzeichnis
DATA_DIR = "/app/data" if os.path.isdir("/app/data") else "."
DB_PATH = os.path.join(DATA_DIR, "data.db")
DB_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DB_URL, echo=False, future=True)

class Base(DeclarativeBase):
    pass

SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)

def init_db():
    from . import models  # noqa
    Base.metadata.create_all(bind=engine)
    _apply_sqlite_migrations()

def _apply_sqlite_migrations():
    with engine.begin() as conn:
        def add_col(sql):
            try:
                conn.exec_driver_sql(sql)
            except Exception as e:
                msg = str(e).lower()
                if "duplicate column name" in msg or "already exists" in msg or "duplicate" in msg:
                    return
                if "no such table" in msg:
                    return
                raise
        add_col("ALTER TABLE tasks ADD COLUMN auto_generated BOOLEAN DEFAULT 1")
        add_col("ALTER TABLE tasks ADD COLUMN booking_hash VARCHAR(64)")
        add_col("ALTER TABLE tasks ADD COLUMN next_arrival VARCHAR(10)")
        add_col("ALTER TABLE tasks ADD COLUMN next_arrival_adults INTEGER")
        add_col("ALTER TABLE tasks ADD COLUMN next_arrival_children INTEGER")
        add_col("ALTER TABLE tasks ADD COLUMN next_arrival_comments TEXT")
        add_col("ALTER TABLE tasks ADD COLUMN next_arrival_guest_name VARCHAR(255)")
        add_col("ALTER TABLE bookings ADD COLUMN guest_name VARCHAR(255)")
        add_col("ALTER TABLE staff ADD COLUMN max_hours_per_month INTEGER DEFAULT 160")
        add_col("ALTER TABLE tasks ADD COLUMN assignment_status VARCHAR(16)")
