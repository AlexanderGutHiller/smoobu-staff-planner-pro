
import os, requests
from typing import Any

BASE_URL = os.getenv("SMOOBU_BASE_URL", "https://login.smoobu.com/api")
API_KEY = os.getenv("SMOOBU_API_KEY", "")

class SmoobuClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or API_KEY
        self.base_url = (base_url or BASE_URL).rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Api-Key": self.api_key,
            "Accept": "application/json",
        }

    def get_reservations(self, date_from: str, date_to: str, page_size: int = 200) -> list[dict[str, Any]]:
        out, page = [], 1
        while True:
            url = f"{self.base_url}/reservations"
            params = {"from": date_from, "to": date_to, "pageSize": page_size, "page": page}
            r = requests.get(url, headers=self._headers(), params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            items = data.get("bookings") or data.get("items") or []
            out.extend(items)
            total = data.get("total_items") or len(out)
            if len(out) >= total or not items:
                break
            page += 1
        return out
