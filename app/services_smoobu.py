
import os, httpx
from typing import Any, Dict, List
BASE_URL = os.getenv("SMOOBU_BASE_URL", "https://api.smoobu.com/api/v1")
API_KEY = os.getenv("SMOOBU_API_KEY", "")
class SmoobuClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or API_KEY
        self.base_url = base_url or BASE_URL
        if not self.api_key:
            raise RuntimeError("SMOOBU_API_KEY is not set")
        self._headers = {"Api-Key": self.api_key}
    async def get_bookings(self, start: str, end: str) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/bookings?start={start}&end={end}"
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url, headers=self._headers)
            r.raise_for_status()
            data = r.json()
            return data.get("bookings", [])
