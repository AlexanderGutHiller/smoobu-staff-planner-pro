import logging
from datetime import datetime
from app.models import Task, Apartment, Booking

logger = logging.getLogger("smoobu")

def build_tasks_from_bookings(db, bookings):
    """
    Erzeugt oder aktualisiert Tasks aus einer Liste von Smoobu-Buchungen.
    Falls ein Task bereits existiert, wird er aktualisiert statt neu erstellt.
    """
    for b in bookings:
        booking_id = b.get("id")
        apt_info = b.get("apartment", {})
        apartment_id = apt_info.get("id")
        guest_name = b.get("guestName", "")
        start_date = b.get("arrivalDate")
        end_date = b.get("departureDate")

        if not (booking_id and apartment_id and start_date and end_date):
            continue  # unvollständige Buchung überspringen

        # Apartment holen oder anlegen
        apartment = db.query(Apartment).filter(Apartment.id == apartment_id).first()
        if not apartment:
            apartment = Apartment(id=apartment_id, name=apt_info.get("name", "Unbekannt"))
            db.add(apartment)

        # Task für Buchung suchen
        existing_task = db.query(Task).filter(Task.booking_id == booking_id).first()
        if existing_task:
            # Aktualisieren
            existing_task.start_time = datetime.fromisoformat(start_date)
            existing_task.end_time = datetime.fromisoformat(end_date)
            existing_task.guest_name = guest_name
        else:
            # Neu anlegen
            task = Task(
                booking_id=booking_id,
                apartment_id=apartment.id,
                start_time=datetime.fromisoformat(start_date),
                end_time=datetime.fromisoformat(end_date),
                guest_name=guest_name,
            )
            db.add(task)

    db.commit()
    logger.info(f"{len(bookings)} bookings processed into tasks.")
