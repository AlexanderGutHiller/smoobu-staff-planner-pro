from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base, Meta

# --- SQLite Datenbank ---
SQLALCHEMY_DATABASE_URL = "sqlite:///./data.db"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# --- Initialisierung ---
def init_db():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        # Stelle sicher, dass Meta-Tabelle existiert
        if not db.query(Meta).first():
            db.add(Meta(key="last_sync", value=None))
            db.commit()

# --- Hilfsfunktionen für Meta-Tabelle ---
def meta_get(db, key: str):
    rec = db.get(Meta, key)
    return rec.value if rec else None

def meta_set(db, key: str, value: str):
    rec = db.get(Meta, key)
    if rec:
        rec.value = value
    else:
        rec = Meta(key=key, value=value)
        db.add(rec)
    db.commit()
