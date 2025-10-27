
import os, secrets, datetime as dt

def new_token(n=16) -> str:
    return secrets.token_hex(n//2)

def today_iso(tz: str | None = None) -> str:
    return dt.datetime.now().date().isoformat()

def now_iso() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
