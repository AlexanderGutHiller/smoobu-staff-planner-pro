
import hashlib, logging
from collections import defaultdict
from sqlalchemy import select
from .db import SessionLocal
from .models import Task, Booking, Apartment

log = logging.getLogger("smoobu")

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
                next_info[b.id] = (nxt.arrival, nxt.adults, nxt.children, nxt.guest_comments, nxt.guest_name)
            else:
                next_info[b.id] = (None, None, None, None, None)
    return next_info

def get_planned_minutes_for(apartment_id: int | None, default=90) -> int:
    with SessionLocal() as s:
        if apartment_id:
            from sqlalchemy import select
            apt = s.execute(select(Apartment).where(Apartment.id == apartment_id)).scalar_one_or_none()
            if apt and getattr(apt, "planned_minutes", None):
                return int(apt.planned_minutes)
    return default

def upsert_tasks_from_bookings(bookings: list[Booking]):
    if not bookings:
        log.info("No bookings to process")
        return
    
    log.info("Processing %d bookings from database", len(bookings))
    clean = []
    for b in bookings:
        log.debug("Checking booking %d: apartment='%s', arrival='%s', departure='%s'", b.id, b.apartment_name, b.arrival, b.departure)
        
        # Prüfe auf leeres oder ungültiges departure
        if not b.departure or not b.departure.strip():
            log.info("❌ Skip booking %d (%s) – no departure", b.id, b.apartment_name)
            continue
        
        # Prüfe auf valides Datumsformat (yyyy-mm-dd)
        if len(b.departure) != 10 or b.departure.count('-') != 2:
            log.info("❌ Skip booking %d (%s) – invalid departure format: '%s'", b.id, b.apartment_name, b.departure)
            continue
        
        # Prüfe auf leeres arrival (Langzeitbuchungen ohne Check-Out)
        if not b.arrival or not b.arrival.strip():
            log.info("❌ Skip booking %d (%s) – no arrival (long-term booking)", b.id, b.apartment_name)
            continue
        
        # Prüfe departure <= arrival (ungültige Buchung)
        if b.departure <= b.arrival:
            log.info("❌ Skip booking %d (%s) – invalid departure <= arrival (%s <= %s)", b.id, b.apartment_name, b.departure, b.arrival)
            continue
        
        # Prüfe auf zu alte Datumsangaben (vor 2020)
        if b.departure < "2020-01-01":
            log.info("❌ Skip booking %d (%s) – departure too old: %s", b.id, b.apartment_name, b.departure)
            continue
        
        log.info("✅ Accept booking %d (%s) - departure: %s", b.id, b.apartment_name, b.departure)
        clean.append(b)
    
    log.info("Filtered: %d valid bookings out of %d total", len(clean), len(bookings))

    booking_ids = [b.id for b in clean]
    next_map = _index_next_arrivals(clean)

    with SessionLocal() as s:
        from sqlalchemy import select
        existing = s.execute(select(Task).where(Task.booking_id.in_(booking_ids))).scalars().all()
        existing_by_booking = {t.booking_id: t for t in existing if t.booking_id is not None}

        for b in clean:
            h = compute_booking_hash(b)
            n_arrival, n_adults, n_children, n_comments, n_guest = next_map.get(b.id, (None, None, None, None, None))
            t = existing_by_booking.get(b.id)
            if t:
                t.date = b.departure
                t.apartment_id = b.apartment_id
                t.booking_hash = h
                t.auto_generated = True
                t.next_arrival = n_arrival
                t.next_arrival_adults = n_adults
                t.next_arrival_children = n_children
                t.next_arrival_comments = (n_comments or "")[:2000] if n_comments else None
                t.next_arrival_guest_name = (n_guest or "")[:255] if n_guest else None
            else:
                s.add(Task(
                    date=b.departure,
                    apartment_id=b.apartment_id,
                    booking_id=b.id,
                    planned_minutes=get_planned_minutes_for(b.apartment_id),
                    status="open",
                    auto_generated=True, booking_hash=h,
                    next_arrival=n_arrival, next_arrival_adults=n_adults,
                    next_arrival_children=n_children,
                    next_arrival_comments=(n_comments or "")[:2000] if n_comments else None,
                    next_arrival_guest_name=(n_guest or "")[:255] if n_guest else None,
                ))

        # Cleanup invalid or stale
        log.info("🧹 Starting cleanup of invalid tasks...")
        removed_count = 0
        for t in s.execute(select(Task)).scalars().all():
            # Entferne Tasks ohne Datum
            if not t.date or not t.date.strip():
                s.delete(t)
                removed_count += 1
                continue
            
            # Prüfe ungültiges Datumsformat
            if len(t.date) != 10 or t.date.count('-') != 2:
                log.info("Removing task %d with invalid date format: %s", t.id, t.date)
                s.delete(t)
                removed_count += 1
                continue
            
            # Prüfe zu alte Tasks (vor 2020)
            if t.date < "2020-01-01":
                log.info("Removing task %d with too old date: %s", t.id, t.date)
                s.delete(t)
                removed_count += 1
                continue
            
            # Prüfe ob zugehörige Buchung noch exists und valide ist
            if t.booking_id:
                b = s.execute(select(Booking).where(Booking.id == t.booking_id)).scalar_one_or_none()
                if b:
                    # Wenn Buchung kein departure mehr hat, lösche Task
                    if not b.departure or not b.departure.strip():
                        log.info("Removing task %d - booking %d has no departure", t.id, t.booking_id)
                        s.delete(t)
                        removed_count += 1
                        continue
                    
                    # Wenn Buchung ungültiges Datum hat, lösche Task
                    if len(b.departure) != 10 or b.departure.count('-') != 2:
                        log.info("Removing task %d - booking %d has invalid departure", t.id, t.booking_id)
                        s.delete(t)
                        removed_count += 1
                        continue
        
        # Entferne ALLE ungültigen Tasks - auch gesperrte!
        current_ids = set(booking_ids)
        for t in s.execute(select(Task)).scalars().all():
            should_delete = False
            reason = ""
            
            # Nur auto-generierte Tasks prüfen
            if t.auto_generated:
                if t.booking_id:
                    # Prüfe ob Buchung in aktueller Liste ist
                    if t.booking_id not in current_ids:
                        should_delete = True
                        reason = f"booking {t.booking_id} no longer exists in Smoobu"
                    else:
                        # Buchung existiert in Liste, prüfe Buchungsdatenbank
                        b = s.execute(select(Booking).where(Booking.id == t.booking_id)).scalar_one_or_none()
                        if not b:
                            should_delete = True
                            reason = f"booking {t.booking_id} not found in database"
                        elif not b.departure or not b.departure.strip():
                            should_delete = True
                            reason = f"booking {t.booking_id} has no departure"
                        elif not b.arrival or not b.arrival.strip():
                            should_delete = True
                            reason = f"booking {t.booking_id} has no arrival"
                        elif len(b.departure) != 10 or b.departure.count('-') != 2:
                            should_delete = True
                            reason = f"booking {t.booking_id} has invalid departure format"
                        elif b.departure <= b.arrival:
                            should_delete = True
                            reason = f"booking {t.booking_id} departure <= arrival"
                elif not t.booking_id and t.date >= "2020-01-01":
                    # Task ohne Buchung (manuell erstellt) - überspringen
                    continue
            
            if should_delete:
                s.delete(t)
                removed_count += 1
                log.info("🗑️ Removing task %d - %s (date: %s, apt: %s, booking: %s)", t.id, reason, t.date, t.apartment_id, t.booking_id)
        
        if removed_count > 0:
            log.info("Cleanup completed: %d invalid/stale tasks removed", removed_count)
        s.commit()
