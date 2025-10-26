
import os, httpx
from typing import Any, Dict, List

BASE_URL = os.getenv("SMOOBU_BASE_URL", "https://login.smoobu.com/api")
API_KEY = os.getenv("SMOOBU_API_KEY", "")

class SmoobuClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or API_KEY
        self.base_url = base_url or BASE_URL
        self._headers = {"Api-Key": self.api_key, "Accept": "application/json", "Cache-Control": "no-cache"} if self.api_key else {}

    async def get_bookings(self, start: str, end: str):
        if not self._headers:
            return []
        out = []
        page = 1
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            while True:
                params = {"from": start, "to": end, "pageSize": 200, "page": page}
                url = f"{self.base_url}/reservations"
                r = await client.get(url, headers=self._headers, params=params)
                r.raise_for_status()
                data = r.json()
                items = data.get("reservations") or data.get("bookings") or []
                out.extend(items)
                total = int(data.get("total_items", 0))
                size = int(data.get("page_size", len(items) or 200))
                if size <= 0 or len(out) >= total:
                    break
                page += 1
        return out
