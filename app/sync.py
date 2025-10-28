import datetime as dt
import logging
from .models import Booking, Task, Apartment

log = logging.getLogger("smoobu")

def _valid_departure(arrival: str, departure: str) -> bool:
    """Hilfsfunktion zur Validierung von Abreisen – vermeidet Phantom-Tasks."""
    if not departure or departure.strip() in ["", "0000-00-00", "null", "None"]:
        return False
    if departure.startswith("1970") or departure <= arrival:
        return False
    return True


def upsert_tasks_from_bookings(bookings):
    """Erzeugt oder aktualisiert Tasks basierend auf den Buchungen."""
    from .db import SessionLocal
    s = SessionLocal()

    apartments = {a.id: a for a in s.query(Apartment).all()}
    existing = {t.booking_id: t for t in s.query(Task).filter(Task.auto_generated == True).all()}

    created, updated, deleted = 0, 0, 0

    seen_booking_ids = set()
    for b in bookings:
        if not b.apartment_id or not _valid_departure(b.arrival, b.departure):
            continue

        seen_booking_ids.add(b.id)
        apt = apartments.get(b.apartment_id)
        planned_minutes = apt.default_duration if apt and apt.default_duration else 90

        if b.id in existing:
            t = existing[b.id]
            if t.apartment_name != b.apartment_name or t.departure != b.departure:
                t.apartment_name = b.apartment_name
                t.departure = b.departure
                updated += 1
        else:
            t = Task(
                booking_id=b.id,
                apartment_id=b.apartment_id,
                apartment_name=b.apartment_name,
                planned_minutes=planned_minutes,
                arrival=b.arrival,
                departure=b.departure,
                guest_name=b.guest_name,
                auto_generated=True,
            )
            s.add(t)
            created += 1

    # Lösche veraltete Tasks
    for t in s.query(Task).filter(Task.auto_generated == True).all():
        if t.booking_id not in seen_booking_ids:
            s.delete(t)
            deleted += 1

    s.commit()
    log.info(f"Tasks neu aufgebaut: {created} neu, {updated} geändert, {deleted} entfernt.")
    s.close()
