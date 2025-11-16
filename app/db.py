
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# Datenbankpfad-Priorität:
# 1) Explizit via ENV DB_PATH (z. B. "/var/data/data.db" auf Render Disk)
# 2) Verzeichnis via ENV DATA_DIR (z. B. "/var/data" oder "/app/data")
# 3) Fly.io Volume "/app/data" falls vorhanden
# 4) Render Disk "/var/data" falls vorhanden
# 5) Fallback: aktuelles Verzeichnis
env_db_path = (os.getenv("DB_PATH") or "").strip()
if env_db_path:
    db_path = env_db_path
else:
    env_data_dir = (os.getenv("DATA_DIR") or "").strip()
    if env_data_dir:
        data_dir = env_data_dir
    elif os.path.isdir("/app/data"):
        data_dir = "/app/data"
    elif os.path.isdir("/var/data"):
        data_dir = "/var/data"
    else:
        data_dir = "."
    db_path = os.path.join(data_dir, "data.db")

DB_URL = f"sqlite:///{db_path}"

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
        add_col("ALTER TABLE staff ADD COLUMN email VARCHAR(255)")
        add_col("ALTER TABLE tasks ADD COLUMN assignment_status VARCHAR(16)")
        add_col("ALTER TABLE staff ADD COLUMN language VARCHAR(8) DEFAULT 'de'")
        add_col("ALTER TABLE tasks ADD COLUMN assign_notified_at VARCHAR(19)")
        add_col("ALTER TABLE staff ADD COLUMN phone VARCHAR(20) DEFAULT ''")
        add_col("ALTER TABLE staff ADD COLUMN whatsapp_opt_in_sent BOOLEAN DEFAULT 0")
        add_col("ALTER TABLE staff ADD COLUMN whatsapp_opt_in_confirmed BOOLEAN DEFAULT 0")
        add_col(\"ALTER TABLE staff ADD COLUMN is_admin BOOLEAN DEFAULT 0\")
        # Create task_series table if not exists
        try:
            conn.exec_driver_sql(\"\"\"\nCREATE TABLE IF NOT EXISTS task_series (\n  id INTEGER PRIMARY KEY AUTOINCREMENT,\n  title VARCHAR(255) DEFAULT '',\n  description TEXT DEFAULT '',\n  apartment_id INTEGER NULL,\n  staff_id INTEGER NULL,\n  planned_minutes INTEGER DEFAULT 60,\n  start_date VARCHAR(10) NOT NULL,\n  start_time VARCHAR(5) DEFAULT '',\n  frequency VARCHAR(16) NOT NULL,\n  interval INTEGER DEFAULT 1,\n  byweekday VARCHAR(64) DEFAULT '',\n  bymonthday VARCHAR(64) DEFAULT '',\n  end_date VARCHAR(10) NULL,\n  count INTEGER NULL,\n  active BOOLEAN DEFAULT 1,\n  created_at VARCHAR(19) DEFAULT ''\n);\n\"\"\")\n        except Exception as e:\n            msg = str(e).lower()\n            if \"already exists\" not in msg:\n                raise\n+        # Add recurrence columns to tasks if missing\n+        add_col(\"ALTER TABLE tasks ADD COLUMN series_id INTEGER\")\n+        add_col(\"ALTER TABLE tasks ADD COLUMN is_recurring BOOLEAN DEFAULT 0\")
