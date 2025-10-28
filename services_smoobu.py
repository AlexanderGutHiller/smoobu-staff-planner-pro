import os
import logging
import requests
from datetime import date

logger = logging.getLogger("smoobu")

SMOOBU_API_KEY = os.getenv("SMOOBU_API_KEY")
SMOOBU_API_BASE = "https://api.smoobu.com"

headers = {
    "X-Api-Key": SMOOBU_API_KEY,
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
    url = f"{SMOOBU_API_BASE}/v1/reservations?from={start_date}&to={end_date}"

    logger.info(f"Smoobu: Fetching bookings from {start_date} to {end_date}")
    logger.info(f"Smoobu: API Key present: {bool(SMOOBU_API_KEY)}")
    logger.info(f"Smoobu: Request URL: {url}")
    logger.info(f"Smoobu: Request headers: {headers}")
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        logger.info(f"Smoobu: Response status code: {response.status_code}")
        logger.info(f"Smoobu: Response headers: {dict(response.headers)}")
        logger.info(f"Smoobu: Response content (first 200 chars): {response.text[:200]}")
        
        response.raise_for_status()
        
        # Überprüfe ob wir JSON bekommen
        if 'application/json' not in response.headers.get('Content-Type', ''):
            logger.error(f"Smoobu: Received non-JSON response. Content-Type: {response.headers.get('Content-Type')}")
            return []
        
        data = response.json()

        # API liefert in ["reservations"] die Liste
        bookings = data.get("reservations", [])
        logger.info(f"Smoobu returned {len(bookings)} reservations")

        return bookings

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching from Smoobu API: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response status: {e.response.status_code}")
            logger.error(f"Response text: {e.response.text[:500]}")
        return []
