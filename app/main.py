import os
import datetime as dt
import logging
from typing import List
from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from openpyxl import Workbook

from .db import init_db, SessionLocal, meta_get, meta_set
from .models import Booking, Apartment, Task, Staff, TimeLog
from .services_smoobu import SmoobuClient
from .sync import upsert_tasks_from_bookings
from .utils import now_iso

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Berlin")
REFRESH_INTERVAL_MINUTES = int(os.getenv("REFRESH_INTERVAL_MINUTES", "60"))
BASE_URL = os.getenv("BASE_URL", "")

log = logging.getLogger("smoobu")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Smoobu Staff Planner Pro (v6.5)")
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="app/templates")

# --- Helper ---
def _parse_iso_date(s: str):
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def date_de(s: str) -> str:
    d = _parse_iso_date(s)
    return d.strftime("%d.%m.%Y") if d else (s or "")

def date_wd_de(s: str) -> str:
    d = _parse_iso_date(s)
    if not d:
        return s or ""
    wd = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    return f"{wd[d.weekday()]}, {d.strftime('%d.%m.%Y')}"

templates.env.filters["date_de"] = date_de
templates.env.filters["date_wd_de"] = date_wd_de

# --- Startup ---
@app.on_event("startup")
async def startup_event():
    init_db()
    if not ADMIN_TOKEN:
        log.warning("ADMIN_TOKEN not set!")
    try:
        await refresh_bookings_job()
    except Exception as e:
        log.exception("Initial import failed: %s", e)
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(refresh_bookings_job, IntervalTrigger(minutes=REFRESH_INTERVAL_MINUTES))
    scheduler.start()

# --- Buchungen & Tasks Sync ---
def _valid_departure(arrival: str, departure: str) -> bool:
    """Strikte Prüfung: nur echte Abreisedaten zulassen."""
    if not departure or departure.strip() in ["", "0000-00-00", "null", "None"]:
        return False
    if departure.startswith("1970") or departure <= arrival:
        return False
    return True

async def refresh_bookings_job():
    client = SmoobuClient()
    start = dt.date.today().isoformat()
    end = (dt.date.today() + dt.timedelta(days=60)).isoformat()
    log.info("Refreshing bookings from %s to %s", start, end)
    items = client.get_reservations(start, end)
    log.info("Fetched %d bookings", len(items))

    with SessionLocal() as db:
        seen_ids = []
        for it in items:
            bid = int(it.get("id"))
            apt = it.get("apartment") or {}
            apt_id = int(apt.get("id")) if apt.get("id") else None
            apt_name = apt.get("name") or ""
            guest = it.get("guest") or {}
            guest_name = guest.get("fullName") or (guest.get("firstName", "") + " " + guest.get("lastName", "")).strip()

            arr = (it.get("arrival") or "")[:10]
            dep = (it.get("departure") or "")[:10]
            if not _valid_departure(arr, dep):
                continue

            if apt_id:
                a = db.get(Apartment, apt_id) or Apartment(id=apt_id)
                a.name = apt_name
                db.add(a)

            b = db.get(Booking, bid) or Booking(id=bid)
            b.apartment_id = apt_id
            b.apartment_name = apt_name
            b.arrival = arr
            b.departure = dep
            b.adults = int(it.get("adults") or 1)
            b.children = int(it.get("children") or 0)
            b.guest_name = guest_name
            db.add(b)
            seen_ids.append(bid)

        # Alte Buchungen entfernen
        existing = [r[0] for r in db.query(Booking.id).all()]
        for bid in existing:
            if bid not in seen_ids:
                db.delete(db.get(Booking, bid))
        db.commit()

        # Tasks neu aufbauen
        bookings = db.query(Booking).all()
        upsert_tasks_from_bookings(bookings)
        db.commit()

        # Letzten Sync speichern
        ts = now_iso()
        meta_set(db, "last_sync", ts)
        log.info("Sync erfolgreich abgeschlossen (%d Buchungen, %s)", len(items), ts)

# --- Routes ---
@app.get("/", response_class=HTMLResponse)
async def root():
    return "<h3>Smoobu Staff Planner Pro</h3><p>Admin: /admin/&lt;TOKEN&gt;</p>"

@app.get("/admin/{token}", response_class=HTMLResponse)
async def admin_home(request: Request, token: str):
    if token != ADMIN_TOKEN:
        return HTMLResponse("<h3>Access denied</h3>", status_code=403)
    with SessionLocal() as db:
        tasks = db.query(Task).all()
        last_sync = meta_get(db, "last_sync") or "unbekannt"
        return templates.TemplateResponse(
            "admin_home.html",
            {"request": request, "tasks": tasks, "last_sync": last_sync,
             "interval": REFRESH_INTERVAL_MINUTES},
        )

@app.get("/admin/{token}/import", response_class=HTMLResponse)
async def admin_import(token: str):
    if token != ADMIN_TOKEN:
        return HTMLResponse("<h3>Access denied</h3>", status_code=403)
    await refresh_bookings_job()
    return RedirectResponse(f"/admin/{token}", status_code=303)

@app.get("/admin/{token}/timelogs")
async def export_timelogs(token: str, month: str = Query(..., description="YYYY-MM")):
    if token != ADMIN_TOKEN:
        return HTMLResponse("<h3>Access denied</h3>", status_code=403)
    wb = Workbook()
    ws = wb.active
    ws.append(["Mitarbeiter", "Datum", "Apartment", "Minuten", "Stundenlohn (€)", "Kosten (€)"])
    total_per_staff = {}
    with SessionLocal() as db:
        logs = db.query(TimeLog).all()
        for t in logs:
            staff = db.get(Staff, t.staff_id)
            if not staff:
                continue
            mins = t.minutes or 0
            cost = round(mins / 60 * (staff.hourly_rate or 0), 2)
            ws.append([staff.name, t.date, t.apartment_name, mins, staff.hourly_rate, cost])
            total_per_staff[staff.name] = total_per_staff.get(staff.name, 0) + cost
        ws2 = wb.create_sheet("Summen")
        ws2.append(["Mitarbeiter", "Summe (€)"])
        for name, val in total_per_staff.items():
            ws2.append([name, round(val, 2)])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f"attachment; filename=timelogs-{month}.xlsx"})

# Cleaner + weitere Admin-Routen wie gehabt (aus v6.4)
