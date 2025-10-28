import os
import logging
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session
from app.db import SessionLocal, init_db
from app.models import Apartment, Booking, Task
from app.services_smoobu import fetch_bookings_from_smoobu
from app.utils import build_tasks_from_bookings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("smoobu")

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")

scheduler = AsyncIOScheduler()
REFRESH_INTERVAL_MINUTES = int(os.getenv("REFRESH_INTERVAL_MINUTES", "60"))

# ---------------------------
# Database Session Management
# ---------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------
# Startup Event
# ---------------------------
@app.on_event("startup")
async def startup_event():
    logger.info("Initializing database...")
    init_db()
    scheduler.add_job(refresh_bookings_job, "interval", minutes=REFRESH_INTERVAL_MINUTES)
    scheduler.start()
    logger.info("Scheduler started.")
    # first import at startup
    try:
        await refresh_bookings_job()
    except Exception as e:
        logger.error(f"Initial import failed: {e}")


# ---------------------------
# Booking Sync Job
# ---------------------------
async def refresh_bookings_job():
    logger.info("Refreshing bookings from Smoobu...")
    db: Session = SessionLocal()
    try:
        today = datetime.today().date()
        until = today + timedelta(days=60)
        bookings = await fetch_bookings_from_smoobu(today, until)
        logger.info(f"Smoobu: {len(bookings)} reservations fetched ({today}..{until})")

        # --- Apartment Upsert ---
        for b in bookings:
            apt_id = b["apartment"]["id"]
            apt_name = b["apartment"]["name"]
            apartment = db.query(Apartment).filter_by(id=apt_id).first()
            if not apartment:
                apartment = Apartment(id=apt_id, name=apt_name, default_duration=90)
                db.add(apartment)
            else:
                # falls Apartmentname sich geändert hat
                apartment.name = apt_name

        # --- Buchungen updaten ---
        db.query(Booking).delete()
        for b in bookings:
            booking = Booking.from_smoobu(b)
            db.add(booking)

        db.commit()

        # --- Tasks neu aufbauen ---
        build_tasks_from_bookings(db)
        db.commit()

        logger.info(f"Fetched {len(bookings)} bookings")
        return True
    except Exception as e:
        logger.exception(f"Error during sync: {e}")
        db.rollback()
    finally:
        db.close()


# ---------------------------
# Routes
# ---------------------------
@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse("<h3>Smoobu Staff Planner</h3><p>Use /admin/&lt;TOKEN&gt;</p>")


@app.get("/admin/{token}", response_class=HTMLResponse)
async def admin_home(request: Request, token: str):
    if token != os.getenv("ADMIN_TOKEN"):
        return HTMLResponse("Unauthorized", status_code=401)
    db = SessionLocal()
    tasks = db.query(Task).all()
    db.close()
    return templates.TemplateResponse("admin_home.html", {"request": request, "tasks": tasks})


@app.get("/admin/{token}/import")
async def admin_import(token: str):
    if token != os.getenv("ADMIN_TOKEN"):
        return HTMLResponse("Unauthorized", status_code=401)
    await refresh_bookings_job()
    return RedirectResponse(url=f"/admin/{token}", status_code=302)
