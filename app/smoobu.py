import os
import requests
import logging

log = logging.getLogger("smoobu")

SMOOBU_BASE_URL = os.getenv("SMOOBU_BASE_URL", "https://api.smoobu.com/v1")
SMOOBU_API_KEY = os.getenv("SMOOBU_API_KEY", "")

class SmoobuClient:
    """Kommuniziert mit der Smoobu REST API."""

    def __init__(self):
        if not SMOOBU_API_KEY:
            raise ValueError("SMOOBU_API_KEY environment variable not set.")
        self.base_url = SMOOBU_BASE_URL.rstrip("/")
        self.headers = {
            "Api-Key": SMOOBU_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def get_reservations(self, start_date: str, end_date: str):
        """Lädt Reservierungen von Smoobu im angegebenen Zeitraum."""
        url = f"{self.base_url}/reservations?from={start_date}&to={end_date}"
        try:
            r = requests.get(url, headers=self.headers, timeout=30)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and "data" in data:
                bookings = data["data"]
            else:
                bookings = data
            log.info(f"Smoobu: {len(bookings)} reservations fetched ({start_date}..{end_date})")
            return bookings
        except Exception as e:
            log.error(f"Smoobu API error: {e}")
            return []# smoobu api integration
