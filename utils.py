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
        apartment_name = apt_info.get("name", "")
        guest_name = b.get("guestName", "")
        arrival_date = b.get("arrivalDate", "")
        departure_date = b.get("departureDate", "")

        if not (booking_id and apartment_id and arrival_date and departure_date):
            continue  # unvollständige Buchung überspringen

        # Apartment holen oder anlegen
        apartment = db.query(Apartment).filter(Apartment.id == apartment_id).first()
        if not apartment:
            apartment = Apartment(id=apartment_id, name=apartment_name, default_duration=90)
            db.add(apartment)

        # Task für Buchung suchen
        existing_task = db.query(Task).filter(Task.booking_id == booking_id).first()
        if existing_task:
            # Aktualisieren
            existing_task.arrival = arrival_date
            existing_task.departure = departure_date
            existing_task.guest_name = guest_name
            existing_task.apartment_name = apartment_name
        else:
            # Neu anlegen
            task = Task(
                booking_id=booking_id,
                apartment_id=apartment.id,
                apartment_name=apartment_name,
                arrival=arrival_date,
                departure=departure_date,
                guest_name=guest_name,
                auto_generated=True,
            )
            db.add(task)

    db.commit()
    logger.info(f"{len(bookings)} bookings processed into tasks.")
