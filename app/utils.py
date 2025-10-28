import secrets, datetime as dt

def new_token(n=16):
    return secrets.token_hex(n//2)

def today_iso():
    return dt.datetime.now().date().isoformat()

def now_iso():
    return dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
