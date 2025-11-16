"""Common dependencies for FastAPI routes"""
import os
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from .db import SessionLocal
from .models import Staff

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

def get_db():
    """Database dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _is_admin_token(token: str, db: Session) -> bool:
    """Check if token is valid admin token"""
    if token == ADMIN_TOKEN:
        return True
    try:
        s = db.query(Staff).filter(
            Staff.magic_token == token,
            Staff.active == True,
            Staff.is_admin == True
        ).first()
        return bool(s)
    except Exception:
        return False

def get_staff_from_token(token: str, db: Session = Depends(get_db)) -> Staff:
    """Get staff member from magic token"""
    staff = db.query(Staff).filter(
        Staff.magic_token == token,
        Staff.active == True
    ).first()
    if not staff:
        raise HTTPException(status_code=403, detail="Invalid token")
    return staff

