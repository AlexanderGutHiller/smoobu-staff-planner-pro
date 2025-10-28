
import hashlib
from collections import defaultdict
from sqlalchemy import select
from .db import SessionLocal
from .models import Task, Booking, Apartment

def compute_booking_hash(b: Booking) -> str:
    payload = f"{b.apartment_id}|{b.arrival}|{b.departure}|{b.adults}|{b.children}|{b.guest_comments}"
    return hashlib.sha1(payload.encode()).hexdigest()

def _index_next_arrivals(bookings: list[Booking]):
    by_apt = defaultdict(list)
    for b in bookings:
        by_apt[b.apartment_id].append(b)
    for k in by_apt:
        by_apt[k].sort(key=lambda x: (x.arrival, x.departure))

    next_info = {}
    for apt, arr in by_apt.items():
        for i, b in enumerate(arr):
            nxt = next((nb for nb in arr if nb.arrival >= b.departure and nb.id != b.id), None)
            if nxt:
                next_info[b.id] = (nxt.arrival, nxt.adults, nxt.children, nxt.guest_comments)
            else:
                next_info[b.id] = (None, None, None, None)
    return next_info

def get_planned_minutes_for(apartment_id: int | None, default=90) -> int:
    with SessionLocal() as s:
        if apartment_id:
            from sqlalchemy import select
            from .models import Apartment
            apt = s.execute(select(Apartment).where(Apartment.id == apartment_id)).scalar_one_or_none()
            if apt and getattr(apt, "planned_minutes", None):
                return int(apt.planned_minutes)
    return default

def upsert_tasks_from_bookings(bookings: list[Booking]):
    if not bookings:
        return
    booking_ids = [b.id for b in bookings]
    next_map = _index_next_arrivals(bookings)

    with SessionLocal() as s:
        existing = s.execute(select(Task).where(Task.booking_id.in_(booking_ids))).scalars().all()
        existing_by_booking = {t.booking_id: t for t in existing if t.booking_id is not None}

        for b in bookings:
            h = compute_booking_hash(b)
            n_arrival, n_adults, n_children, n_comments = next_map.get(b.id, (None, None, None, None))
            t = existing_by_booking.get(b.id)
            if t:
                if not t.locked:
                    t.date = b.departure
                    t.apartment_id = b.apartment_id
                    # planned_minutes NICHT überschreiben (nur bei neuen Tasks)
                    t.booking_hash = h
                    t.auto_generated = True
                    t.next_arrival = n_arrival
                    t.next_arrival_adults = n_adults
                    t.next_arrival_children = n_children
                    t.next_arrival_comments = (n_comments or "")[:2000] if n_comments else None
            else:
                s.add(Task(
                    date=b.departure,
                    apartment_id=b.apartment_id,
                    booking_id=b.id,
                    planned_minutes=get_planned_minutes_for(b.apartment_id),
                    status="open",
                    auto_generated=True, locked=False, booking_hash=h,
                    next_arrival=n_arrival, next_arrival_adults=n_adults,
                    next_arrival_children=n_children,
                    next_arrival_comments=(n_comments or "")[:2000] if n_comments else None,
                ))

        # remove stale auto-generated, unlocked tasks whose booking vanished
        stale = s.execute(select(Task)).scalars().all()
        current_ids = set(booking_ids)
        for t in stale:
            if t.auto_generated and (not t.locked) and (t.booking_id and t.booking_id not in current_ids):
                s.delete(t)
        s.commit()
