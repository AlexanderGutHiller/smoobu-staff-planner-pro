import datetime as dt
import secrets
import string

# --- Erzeugt einen ISO-Zeitstempel (lokal) ---
def now_iso():
    """Gibt aktuellen Zeitstempel im ISO-Format mit Zeitzone zurück."""
    return dt.datetime.now().replace(microsecond=0).isoformat()

# --- Magic-Link Token ---
def new_token(length: int = 24) -> str:
    """Erzeugt zufälligen, URL-sicheren Token."""
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))
