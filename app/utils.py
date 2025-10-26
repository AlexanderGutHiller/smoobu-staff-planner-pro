import secrets, datetime as dt

def new_token():
    return secrets.token_urlsafe(32)

def today_iso():
    return dt.date.today().isoformat()

def now_iso():
    return dt.datetime.utcnow().replace(microsecond=0).isoformat(sep=' ')
