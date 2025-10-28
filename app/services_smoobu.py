import os
import logging
import requests
from datetime import date

logger = logging.getLogger("smoobu")

SMOOBU_API_KEY = os.getenv("SMOOBU_API_KEY")
SMOOBU_API_BASE = "https://api.smoobu.com/v1"

headers = {
    "Api-Key": SMOOBU_API_KEY,
    "Content-Type": "application/json"
}


# --------------------------------------------------
# Hauptfunktion, die von main.py aufgerufen wird
# --------------------------------------------------
async def fetch_bookings_from_smoobu(start_date: date, end_date: date):
    """
    Ruft Buchungen im angegebenen Zeitraum aus der Smoobu API ab.
    Gibt eine Liste von dicts mit Buchungsdaten zurück.
    """
    url = f"{SMOOBU_API_BASE}/reservations?from={start_date}&to={end_date}"

    logger.info(f"Smoobu: Fetching bookings from {start_date} to {end_date}")
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        # API liefert in ["reservations"] die Liste
        bookings = data.get("reservations", [])
        logger.info(f"Smoobu returned {len(bookings)} reservations")

        return bookings

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching from Smoobu API: {e}")
        return []
