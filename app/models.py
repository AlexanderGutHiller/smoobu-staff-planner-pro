from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Float
from sqlalchemy.orm import declarative_base, relationship
import datetime as dt

Base = declarative_base()

# --- Neue Meta-Tabelle für Systemwerte (z. B. letzter Sync) ---
class Meta(Base):
    __tablename__ = "meta"
    key = Column(String, primary_key=True)
    value = Column(String, nullable=True)

# --- Stammdaten ---
class Apartment(Base):
    __tablename__ = "apartments"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    default_duration = Column(Integer, default=90)  # geplante Minuten pro Reinigung

class Staff(Base):
    __tablename__ = "staff"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    token = Column(String, nullable=False, unique=True)
    hourly_rate = Column(Float, default=15.0)
    max_hours_per_month = Column(Float, default=160.0)
    is_active = Column(Boolean, default=True)

# --- Buchungen von Smoobu ---
class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True)
    apartment_id = Column(Integer, ForeignKey("apartments.id"))
    apartment_name = Column(String)
    arrival = Column(String)
    departure = Column(String)
    adults = Column(Integer)
    children = Column(Integer)
    guest_name = Column(String)

# --- Reinigungs-Tasks ---
class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=True)
    apartment_id = Column(Integer, ForeignKey("apartments.id"))
    apartment_name = Column(String)
    planned_minutes = Column(Integer, default=90)
    arrival = Column(String)
    departure = Column(String)
    guest_name = Column(String)
    assigned_staff_id = Column(Integer, ForeignKey("staff.id"), nullable=True)
    locked = Column(Boolean, default=False)
    done = Column(Boolean, default=False)
    auto_generated = Column(Boolean, default=True)

# --- Zeitprotokolle ---
class TimeLog(Base):
    __tablename__ = "timelogs"
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"))
    staff_id = Column(Integer, ForeignKey("staff.id"))
    apartment_name = Column(String)
    date = Column(String, default=lambda: dt.date.today().isoformat())
    minutes = Column(Integer, default=0)
