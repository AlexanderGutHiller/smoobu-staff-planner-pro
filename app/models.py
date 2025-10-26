
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Integer, Float, Boolean, ForeignKey, Text
from .db import Base

class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    apartment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    apartment_name: Mapped[str] = mapped_column(String(255), default="")
    arrival: Mapped[str] = mapped_column(String(10), default="")
    departure: Mapped[str] = mapped_column(String(10), default="")
    nights: Mapped[int] = mapped_column(Integer, default=0)
    adults: Mapped[int] = mapped_column(Integer, default=1)
    children: Mapped[int] = mapped_column(Integer, default=0)
    guest_comments: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="")

class Staff(Base):
    __tablename__ = "staff"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    hourly_rate: Mapped[float] = mapped_column(Float, default=15.0)
    max_hours_month: Mapped[float] = mapped_column(Float, default=160.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    magic_token: Mapped[str] = mapped_column(String(64), unique=True)

class Apartment(Base):
    __tablename__ = "apartments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    smoobu_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    planned_minutes: Mapped[int] = mapped_column(Integer, default=90)

class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String(10))
    start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    planned_minutes: Mapped[int] = mapped_column(Integer, default=90)
    notes: Mapped[str] = mapped_column(Text, default="")
    extras_json: Mapped[str] = mapped_column(Text, default="{}")
    apartment_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("apartments.id"))
    booking_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("bookings.id"))
    assigned_staff_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("staff.id"))
    status: Mapped[str] = mapped_column(String(16), default="open")

class TimeLog(Base):
    __tablename__ = "timelogs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("tasks.id"))
    staff_id: Mapped[int] = mapped_column(Integer, ForeignKey("staff.id"))
    started_at: Mapped[str] = mapped_column(String(19))  # 'YYYY-MM-DD HH:MM:SS' UTC
    ended_at: Mapped[str | None] = mapped_column(String(19), nullable=True)
    actual_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
