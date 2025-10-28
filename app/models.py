
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Integer, Float, Boolean, ForeignKey, Text
from .db import Base

class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    apartment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    apartment_name: Mapped[str] = mapped_column(String(255), default="")
    arrival: Mapped[str] = mapped_column(String(10), default="")     # yyyy-mm-dd
    departure: Mapped[str] = mapped_column(String(10), default="")   # yyyy-mm-dd
    nights: Mapped[int] = mapped_column(Integer, default=0)
    adults: Mapped[int] = mapped_column(Integer, default=1)
    children: Mapped[int] = mapped_column(Integer, default=0)
    guest_comments: Mapped[str] = mapped_column(Text, default="")
    guest_name: Mapped[str] = mapped_column(String(255), default="")

class Apartment(Base):
    __tablename__ = "apartments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(255), default="")
    planned_minutes: Mapped[int] = mapped_column(Integer, default=90)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Staff(Base):
    __tablename__ = "staff"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    hourly_rate: Mapped[float] = mapped_column(Float, default=0.0)
    max_hours_per_month: Mapped[int] = mapped_column(Integer, default=160)
    magic_token: Mapped[str] = mapped_column(String(32), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String(10))  # yyyy-mm-dd
    start_time: Mapped[str] = mapped_column(String(5), default="")   # optional HH:MM
    planned_minutes: Mapped[int] = mapped_column(Integer, default=90)
    notes: Mapped[str] = mapped_column(Text, default="")
    extras_json: Mapped[str] = mapped_column(Text, default="{}")
    apartment_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("apartments.id"))
    booking_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("bookings.id"))
    assigned_staff_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("staff.id"))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|running|done

    auto_generated: Mapped[bool] = mapped_column(Boolean, default=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    booking_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    next_arrival: Mapped[str | None] = mapped_column(String(10), nullable=True)
    next_arrival_adults: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_arrival_children: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_arrival_comments: Mapped[str | None] = mapped_column(Text, nullable=True)

class TimeLog(Base):
    __tablename__ = "timelogs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("tasks.id"))
    staff_id: Mapped[int] = mapped_column(Integer, ForeignKey("staff.id"))
    started_at: Mapped[str] = mapped_column(String(19))  # yyyy-mm-dd HH:MM:SS
    ended_at: Mapped[str | None] = mapped_column(String(19), nullable=True)
    actual_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
