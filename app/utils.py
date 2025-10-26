
import secrets, datetime as dt

def new_token():
    return secrets.token_urlsafe(32)

def today_iso():
    return dt.date.today().isoformat()

def now_iso():
    return dt.datetime.utcnow().replace(microsecond=0).isoformat(sep=' ')

def pick_lang(accept_language: str | None) -> str:
    al = (accept_language or "").lower()
    for code in ["de","bg","ro","ru","en"]:
        if code in al: return code
    return "en"
