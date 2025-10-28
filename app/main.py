
import os, json, datetime as dt, csv, io, logging
from typing import List, Optional, Dict
from fastapi import FastAPI, Request, Depends, Form, HTTPException, Query
from fastapi.responses import RedirectResponse, StreamingResponse, PlainTextResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .db import init_db, SessionLocal
from .models import Booking, Staff, Apartment, Task, TimeLog
from .services_smoobu import SmoobuClient
from .utils import new_token, today_iso, now_iso
from .sync import upsert_tasks_from_bookings

def detect_language(request: Request) -> str:
    """Erkenne Browser-Sprache aus Cookie, Query-Parameter oder Accept-Language Header"""
    # Zuerst Cookie überprüfen
    lang_cookie = request.cookies.get("lang", "")
    if lang_cookie in ["de", "en", "fr", "it", "es", "ro", "ru", "bg"]:
        return lang_cookie
    
    # Dann Query-Parameter überprüfen
    lang_query = request.query_params.get("lang", "")
    if lang_query in ["de", "en", "fr", "it", "es", "ro", "ru", "bg"]:
        return lang_query
    
    # Dann Accept-Language Header
    accept_lang = request.headers.get("accept-language", "de").lower()
    if "en" in accept_lang:
        return "en"
    elif "fr" in accept_lang:
        return "fr"
    elif "it" in accept_lang:
        return "it"
    elif "es" in accept_lang:
        return "es"
    elif "ro" in accept_lang:
        return "ro"
    elif "ru" in accept_lang:
        return "ru"
    elif "bg" in accept_lang:
        return "bg"
    return "de"  # Default: Deutsch

def get_translations(lang: str) -> Dict[str, str]:
    """Übersetzungen für verschiedene Sprachen"""
    translations = {
        "de": {
            "tasks": "Einsätze", "team": "Team", "apartments": "Apartments", "import_now": "Import jetzt",
            "cleanup": "Bereinigen", "date": "Datum", "apartment": "Apartment", "planned": "Geplant",
            "status": "Status", "actual": "Tatsächlich", "next_arrival": "Nächste Anreise", "locked": "Lock",
            "save": "Speichern", "today": "Heute", "week": "Diese Woche", "month": "Dieser Monat",
            "next7": "Nächste 7 Tage", "all": "Alle", "lock": "Gesperrt", "unlock": "Offen"
        },
        "en": {
            "tasks": "Tasks", "team": "Team", "apartments": "Apartments", "import_now": "Import now",
            "cleanup": "Clean up", "date": "Date", "apartment": "Apartment", "planned": "Planned",
            "status": "Status", "actual": "Actual", "next_arrival": "Next Arrival", "locked": "Lock",
            "save": "Save", "today": "Today", "week": "This Week", "month": "This Month",
            "next7": "Next 7 Days", "all": "All", "lock": "Locked", "unlock": "Open"
        },
        "ro": {
            "tasks": "Sarcini", "team": "Echipa", "apartments": "Apartamente", "import_now": "Importă acum",
            "cleanup": "Curățare", "date": "Dată", "apartment": "Apartament", "planned": "Planificat",
            "status": "Status", "actual": "Real", "next_arrival": "Următoarea sosire", "locked": "Blocat",
            "save": "Salvează", "today": "Azi", "week": "Săptămâna aceasta", "month": "Luna aceasta",
            "next7": "Următoarele 7 zile", "all": "Toate", "lock": "Blocat", "unlock": "Deschis"
        },
        "ru": {
            "tasks": "Задачи", "team": "Команда", "apartments": "Апартаменты", "import_now": "Импорт сейчас",
            "cleanup": "Очистка", "date": "Дата", "apartment": "Апартамент", "planned": "Запланировано",
            "status": "Статус", "actual": "Фактически", "next_arrival": "Следующий приезд", "locked": "Заблокировано",
            "save": "Сохранить", "today": "Сегодня", "week": "На этой неделе", "month": "В этом месяце",
            "next7": "Следующие 7 дней", "all": "Все", "lock": "Заблокировано", "unlock": "Открыто"
        },
        "bg": {
            "tasks": "Задачи", "team": "Екип", "apartments": "Апартаменти", "import_now": "Импортирай сега",
            "cleanup": "Почистване", "date": "Дата", "apartment": "Апартамент", "planned": "Планирано",
            "status": "Статус", "actual": "Действително", "next_arrival": "Следващо пристигане", "locked": "Заключено",
            "save": "Запази", "today": "Днес", "week": "Тази седмица", "month": "Този месец",
            "next7": "Следващите 7 дни", "all": "Всички", "lock": "Заключено", "unlock": "Отворено"
        }
    }
    return translations.get(lang, translations["de"])

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Berlin")
REFRESH_INTERVAL_MINUTES = int(os.getenv("REFRESH_INTERVAL_MINUTES", "60"))
BASE_URL = os.getenv("BASE_URL", "")

log = logging.getLogger("smoobu")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Smoobu Staff Planner Pro (v6.3)")

if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="app/templates")

def _parse_iso_date(s: str):
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def date_de(s: str) -> str:
    d = _parse_iso_date(s)
    return d.strftime("%d.%m.%Y") if d else (s or "")

def date_wd_de(s: str, style: str = "short") -> str:
    d = _parse_iso_date(s)
    if not d:
        return s or ""
    wd_short = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    wd_long  = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
    name = wd_long[d.weekday()] if style == "long" else wd_short[d.weekday()]
    return f"{name}, {d.strftime('%d.%m.%Y')}"

templates.env.filters["date_de"] = date_de
templates.env.filters["date_wd_de"] = date_wd_de

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.on_event("startup")
async def startup_event():
    init_db()
    if not ADMIN_TOKEN:
        log.warning("ADMIN_TOKEN not set! Admin UI will be inaccessible.")
    try:
        await refresh_bookings_job()
    except Exception as e:
        log.exception("Initial import failed: %s", e)
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(refresh_bookings_job, IntervalTrigger(minutes=REFRESH_INTERVAL_MINUTES))
    scheduler.start()

def _daterange(days=60):
    start = dt.date.today()
    end = start + dt.timedelta(days=days)
    return start.isoformat(), end.isoformat()

def _best_guest_name(it: dict) -> str:
    guest = it.get("guest") or {}
    full = guest.get("fullName") or ""
    if full:
        return full
    fn = guest.get("firstName", "") or it.get("firstName", "")
    ln = guest.get("lastName", "") or it.get("lastName", "")
    name = (fn + " " + ln).strip()
    if name:
        return name
    return it.get("name") or it.get("contactName") or ""

async def refresh_bookings_job():
    client = SmoobuClient()
    start, end = _daterange(60)
    log.info("🔄 Starting refresh: %s to %s", start, end)
    items = client.get_reservations(start, end)
    log.info("📥 Fetched %d bookings from Smoobu", len(items))
    with SessionLocal() as db:
        seen_booking_ids: List[int] = []
        seen_apartment_ids: List[int] = []
        for it in items:
            b_id = int(it.get("id"))
            apt = it.get("apartment") or {}
            apt_id = int(apt.get("id")) if apt.get("id") is not None else None
            apt_name = apt.get("name") or ""
            guest_name = _best_guest_name(it)
            arrival = (it.get("arrival") or "")[:10]
            departure = (it.get("departure") or "")[:10]

            # Check if booking is cancelled or blocked
            is_blocked = it.get("isBlockedBooking", False) or it.get("blocked", False)
            status = it.get("status", "").lower() if it.get("status") else ""
            cancelled = status == "cancelled" or it.get("cancelled", False)
            is_internal = it.get("isInternal", False)
            
            # Check for various status
            is_draft = status == "draft"
            is_pending = status == "pending"
            is_on_hold = status == "on hold" or status == "on_hold"
            
            log.debug("Smoobu booking %d: apt='%s', arrival='%s', departure='%s', status='%s'", 
                     b_id, apt_name, arrival, departure, it.get("status"))
            
            # Log ALL fields for Romantik to debug
            if apt_name and "romantik" in apt_name.lower() and "2025-10-29" in departure:
                log.warning("🎯 ROMANTIK FULL BOOKING DATA: %s", it)
                log.warning("🎯 Status fields: type='%s', status='%s', cancelled=%s, blocked=%s, internal=%s, draft=%s, pending=%s, on_hold=%s", 
                           it.get("type"), status, cancelled, is_blocked, is_internal, is_draft, is_pending, is_on_hold)

            # Check booking type FIRST - before we update or create the booking
            booking_type = it.get("type", "").lower()
            
            # Check for cancelled, blocked, internal, draft, pending, on-hold bookings OR cancellation type - SKIP and DELETE these!
            should_skip = False
            reason = ""
            
            if booking_type == "cancellation":
                should_skip = True
                reason = "cancellation type"
            elif cancelled:
                should_skip = True
                reason = "cancelled"
            elif is_blocked:
                should_skip = True
                reason = "blocked"
            elif is_internal:
                should_skip = True
                reason = "internal"
            elif is_draft:
                should_skip = True
                reason = "draft"
            elif is_pending:
                should_skip = True
                reason = "pending"
            elif is_on_hold:
                should_skip = True
                reason = "on-hold"
            
            # Check for invalid bookings - also skip and delete
            if not departure or not departure.strip():
                log.info("⛔ SKIP INVALID booking %d (%s) - NO DEPARTURE, arrival='%s'", b_id, apt_name, arrival)
                should_skip = True
                reason = "invalid (no departure)"
            elif not arrival or not arrival.strip():
                log.info("⛔ SKIP INVALID booking %d (%s) - NO ARRIVAL, departure='%s'", b_id, apt_name, departure)
                should_skip = True
                reason = "invalid (no arrival)"
            elif departure <= arrival:
                log.info("⛔ SKIP INVALID booking %d (%s) - departure <= arrival ('%s' <= '%s')", b_id, apt_name, departure, arrival)
                should_skip = True
                reason = "invalid (departure <= arrival)"
            
            if should_skip:
                log.info("⛔ SKIP %s booking %d (%s) - arrival: %s, departure: %s", reason, b_id, apt_name, arrival, departure)
                # Delete existing booking if it exists
                b_existing = db.get(Booking, b_id)
                if b_existing:
                    db.delete(b_existing)
                    log.info("🗑️ Deleted existing booking %d from database", b_id)
                continue
            
            # Only log valid bookings
            log.info("✓ Valid booking %d (%s) - arrival: %s, departure: %s", b_id, apt_name, arrival, departure)
            
            if apt_id is not None and apt_id not in seen_apartment_ids:
                a = db.get(Apartment, apt_id)
                if not a:
                    a = Apartment(id=apt_id, name=apt_name, planned_minutes=90, active=True)
                    db.add(a)
                else:
                    a.name = apt_name or a.name
                seen_apartment_ids.append(apt_id)

            b = db.get(Booking, b_id)
            if not b:
                b = Booking(id=b_id)
                db.add(b)
            b.apartment_id = apt_id
            b.apartment_name = apt_name or ""
            b.arrival = (it.get("arrival") or "")[:10]
            b.departure = (it.get("departure") or "")[:10]
            b.nights = int(it.get("nights") or 0)
            b.adults = int(it.get("adults") or 1)
            b.children = int(it.get("children") or 0)
            b.guest_comments = (it.get("guestComments") or it.get("comments") or "")[:2000]
            b.guest_name = guest_name or ""
            
            seen_booking_ids.append(b_id)

        existing_ids = [row[0] for row in db.query(Booking.id).all()]
        for bid in existing_ids:
            if bid not in seen_booking_ids:
                db.delete(db.get(Booking, bid))

        db.commit()

        bookings = db.query(Booking).all()
        log.info("📋 Processing %d bookings from database", len(bookings))
        upsert_tasks_from_bookings(bookings)

        removed = 0
        for t in db.query(Task).all():
            if not t.date or not t.date.strip():
                db.delete(t); removed += 1
        if removed:
            log.info("🧹 Cleanup: %d Tasks ohne Datum entfernt.", removed)
        db.commit()
        log.info("✅ Refresh completed successfully")

@app.get("/", response_class=HTMLResponse)
async def root():
    return "<html><head><link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' rel='stylesheet'></head><body class='p-4' style='font-family:system-ui;'><h1>Smoobu Staff Planner Pro</h1><p>Service läuft. Admin-UI: <code>/admin/&lt;ADMIN_TOKEN&gt;</code></p><p>Health: <a href='/health'>/health</a></p></body></html>"

@app.get("/health")
async def health():
    return {"ok": True, "time": now_iso()}

@app.get("/set-language")
async def set_language(lang: str, redirect: str = "/"):
    """Setze die Sprache als Cookie und leite weiter"""
    if lang not in ["de", "en", "fr", "it", "es", "ro", "ru", "bg"]:
        lang = "de"
    
    # Erstelle Response mit Redirect
    response = RedirectResponse(url=redirect)
    response.set_cookie(
        key="lang",
        value=lang,
        max_age=365*24*60*60,  # 1 Jahr
        httponly=False,
        secure=False,
        samesite="lax"
    )
    return response

# -------------------- Admin UI --------------------
@app.get("/admin/{token}")
async def admin_home(request: Request, token: str, date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None), staff_id: Optional[int] = Query(None), apartment_id: Optional[int] = Query(None), db=Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403)
    
    lang = detect_language(request)
    trans = get_translations(lang)
    
    q = db.query(Task)
    if date_from: q = q.filter(Task.date >= date_from)
    if date_to: q = q.filter(Task.date <= date_to)
    if staff_id: q = q.filter(Task.assigned_staff_id == staff_id)
    if apartment_id: q = q.filter(Task.apartment_id == apartment_id)
    tasks = q.order_by(Task.date, Task.id).all()
    staff = db.query(Staff).filter(Staff.active==True).all()
    apts = db.query(Apartment).filter(Apartment.active==True).all()
    apt_map = {a.id: a.name for a in apts}
    bookings = db.query(Booking).all()
    book_map = {b.id: b.guest_name for b in bookings}
    booking_details_map = {b.id: {'adults': b.adults or 0, 'children': b.children or 0, 'guest_name': b.guest_name or ''} for b in bookings}
    
    # Timelog-Daten für jedes Task
    timelog_map = {}
    for t in tasks:
        tl = db.query(TimeLog).filter(TimeLog.task_id==t.id).order_by(TimeLog.id.desc()).first()
        if tl:
            timelog_map[t.id] = {
                'actual_minutes': tl.actual_minutes,
                'started_at': tl.started_at,
                'ended_at': tl.ended_at
            }
    
    base_url = BASE_URL.rstrip("/")
    if not base_url:
        base_url = f"{request.url.scheme}://{request.url.hostname}" + (f":{request.url.port}" if request.url.port else "")
    return templates.TemplateResponse("admin_home.html", {"request": request, "token": token, "tasks": tasks, "staff": staff, "apartments": apts, "apt_map": apt_map, "book_map": book_map, "booking_details_map": booking_details_map, "timelog_map": timelog_map, "base_url": base_url, "lang": lang, "t": trans})

@app.get("/admin/{token}/staff")
async def admin_staff(request: Request, token: str, db=Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403)
    lang = detect_language(request)
    trans = get_translations(lang)
    staff = db.query(Staff).order_by(Staff.name).all()
    base_url = BASE_URL.rstrip("/")
    if not base_url:
        base_url = f"{request.url.scheme}://{request.url.hostname}" + (f":{request.url.port}" if request.url.port else "")
    return templates.TemplateResponse("admin_staff.html", {"request": request, "token": token, "staff": staff, "base_url": base_url, "lang": lang, "t": trans})

@app.post("/admin/{token}/staff/add")
async def admin_staff_add(token: str, name: str = Form(...), hourly_rate: float = Form(0.0), max_hours_per_month: int = Form(160), db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    s = Staff(name=name, hourly_rate=hourly_rate, max_hours_per_month=max_hours_per_month, magic_token=new_token(16), active=True)
    db.add(s); db.commit()
    return RedirectResponse(url=f"/admin/{token}/staff", status_code=303)

@app.post("/admin/{token}/staff/toggle")
async def admin_staff_toggle(token: str, staff_id: int = Form(...), db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    s = db.get(Staff, staff_id); s.active = not s.active; db.commit()
    return RedirectResponse(url=f"/admin/{token}/staff", status_code=303)

@app.post("/admin/{token}/task/assign")
async def admin_task_assign(token: str, task_id: int = Form(...), staff_id_raw: str = Form(""), db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    staff_id: Optional[int] = int(staff_id_raw) if staff_id_raw.strip() else None
    t.assigned_staff_id = staff_id
    db.commit()
    return RedirectResponse(url=f"/admin/{token}", status_code=303)

@app.post("/admin/{token}/task/lock")
async def admin_task_lock(token: str, task_id: int = Form(...), lock: int = Form(1), db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    t = db.get(Task, task_id); t.locked = bool(int(lock)); db.commit()
    return RedirectResponse(url=f"/admin/{token}", status_code=303)

@app.get("/admin/{token}/apartments")
async def admin_apartments(request: Request, token: str, db=Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403)
    lang = detect_language(request)
    trans = get_translations(lang)
    apts = db.query(Apartment).order_by(Apartment.name).all()
    return templates.TemplateResponse("admin_apartments.html", {"request": request, "token": token, "apartments": apts, "lang": lang, "t": trans})

@app.post("/admin/{token}/apartments/update")
async def admin_apartments_update(token: str, apartment_id: int = Form(...), planned_minutes: int = Form(...), db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    a = db.get(Apartment, apartment_id)
    a.planned_minutes = int(planned_minutes)
    db.commit()
    return RedirectResponse(url=f"/admin/{token}/apartments", status_code=303)

@app.post("/admin/{token}/apartments/apply")
async def admin_apartments_apply(token: str, apartment_id: int = Form(...), db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    a = db.get(Apartment, apartment_id)
    if not a:
        raise HTTPException(status_code=404, detail="Apartment nicht gefunden")
    
    # Get today's date
    today_iso = dt.date.today().isoformat()
    
    # Update all tasks for this apartment that are today or in the future
    # Only update unlocked tasks
    tasks = db.query(Task).filter(
        Task.apartment_id == apartment_id,
        Task.date >= today_iso,
        Task.locked == False
    ).all()
    
    updated = 0
    for t in tasks:
        t.planned_minutes = a.planned_minutes
        updated += 1
    
    db.commit()
    log.info("Updated %d tasks for apartment %s to %d minutes", updated, a.name, a.planned_minutes)
    return RedirectResponse(url=f"/admin/{token}/apartments", status_code=303)

@app.get("/admin/{token}/import")
async def admin_import(token: str, db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    await refresh_bookings_job()
    return PlainTextResponse("Import done.")

@app.get("/admin/{token}/cleanup_tasks")
async def admin_cleanup_tasks(token: str, date: str, db=Depends(get_db)):
    """Manuelles Löschen von Tasks an einem bestimmten Datum"""
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    
    removed_count = 0
    tasks = db.query(Task).filter(Task.date == date, Task.auto_generated == True).all()
    
    for t in tasks:
        db.delete(t)
        removed_count += 1
        log.info("Removed task %d for date %s (apartment: %s)", t.id, date, t.apartment_id)
    
    db.commit()
    return PlainTextResponse(f"Removed {removed_count} tasks for date {date}.")

@app.get("/admin/{token}/cleanup")
async def admin_cleanup(token: str, db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    
    removed_count = 0
    all_bookings = {b.id for b in db.query(Booking).all()}
    log.info("🔍 Cleanup started. Checking %d tasks against %d bookings", db.query(Task).count(), len(all_bookings))
    
    # Finde ALLE ungültigen Tasks
    for t in db.query(Task).all():
        should_delete = False
        reason = ""
        
        # Nur auto-generierte Tasks prüfen
        if t.auto_generated and t.booking_id:
            b = db.get(Booking, t.booking_id)
            
            # Wenn Buchung nicht mehr existiert
            if not b or t.booking_id not in all_bookings:
                should_delete = True
                reason = f"booking {t.booking_id} does not exist"
            # Wenn Buchung kein departure hat
            elif not b.departure or not b.departure.strip():
                should_delete = True
                reason = f"booking {t.booking_id} has no departure"
            # Wenn Buchung kein arrival hat
            elif not b.arrival or not b.arrival.strip():
                should_delete = True
                reason = f"booking {t.booking_id} has no arrival"
            # Wenn departure format ungültig
            elif len(b.departure) != 10 or b.departure.count('-') != 2:
                should_delete = True
                reason = f"booking {t.booking_id} has invalid departure format"
            # Wenn arrival format ungültig
            elif len(b.arrival) != 10 or b.arrival.count('-') != 2:
                should_delete = True
                reason = f"booking {t.booking_id} has invalid arrival format"
            # Wenn departure <= arrival
            elif b.departure <= b.arrival:
                should_delete = True
                reason = f"booking {t.booking_id} departure <= arrival"
        
        if should_delete:
            db.delete(t)
            removed_count += 1
            log.info("🗑️ Removing invalid task %d (date: %s, apt: %s, booking: %s) - %s", t.id, t.date, t.apartment_id, t.booking_id, reason)
    
    db.commit()
    log.info("✅ Cleanup done. Removed %d invalid tasks", removed_count)
    return PlainTextResponse(f"Cleanup done. Removed {removed_count} invalid tasks (including locked ones). Check logs for details.")

@app.get("/admin/{token}/export")
async def admin_export(token: str, month: str, db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    apts = db.query(Apartment).all()
    apt_map = {a.id: a.name for a in apts}
    rows = []
    for t in db.query(Task).order_by(Task.date, Task.id).all():
        if not t.date.startswith(month): continue
        staff = db.get(Staff, t.assigned_staff_id) if t.assigned_staff_id else None
        rate = float(staff.hourly_rate) if staff else 0.0
        actual = 0
        tl = db.query(TimeLog).filter(TimeLog.task_id==t.id, TimeLog.actual_minutes!=None).order_by(TimeLog.id.desc()).first()
        if tl: actual = int(tl.actual_minutes)
        cost = round((actual/60.0)*rate, 2)
        rows.append({
            "date": t.date,
            "apartment_id": t.apartment_id,
            "apartment_name": apt_map.get(t.apartment_id, ""),
            "staff": staff.name if staff else "",
            "planned_minutes": t.planned_minutes,
            "actual_minutes": actual,
            "hourly_rate": rate,
            "cost_eur": cost,
            "notes": t.notes,
            "extras": t.extras_json,
            "next_arrival": t.next_arrival or "",
            "next_arrival_adults": t.next_arrival_adults or 0,
            "next_arrival_children": t.next_arrival_children or 0,
        })
    headers = list(rows[0].keys()) if rows else ["date","apartment_id","apartment_name","staff","planned_minutes","actual_minutes","hourly_rate","cost_eur","notes","extras","next_arrival","next_arrival_adults","next_arrival_children"]
    output = io.StringIO()
    w = csv.DictWriter(output, fieldnames=headers)
    w.writeheader()
    for r in rows: w.writerow(r)
    return StreamingResponse(iter([output.getvalue().encode('utf-8')]), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=report-{month}.csv"})

# -------------------- Cleaner --------------------
@app.get("/cleaner/{token}")
async def cleaner_home(request: Request, token: str, show_done: int = 0, db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    q = db.query(Task).filter(Task.assigned_staff_id==s.id)
    if not show_done:
        q = q.filter(Task.status != "done")
    tasks = q.order_by(Task.date, Task.id).all()
    apts = db.query(Apartment).all()
    apt_map = {a.id: a.name for a in apts}
    bookings = db.query(Booking).all()
    book_map = {b.id: b.guest_name for b in bookings}
    booking_details_map = {b.id: {'adults': b.adults or 0, 'children': b.children or 0, 'guest_name': b.guest_name or ''} for b in bookings}
    month = dt.date.today().strftime("%Y-%m")
    minutes = 0
    logs = db.query(TimeLog).filter(TimeLog.staff_id==s.id, TimeLog.actual_minutes!=None).all()
    for tl in logs:
        if tl.started_at[:7]==month and tl.actual_minutes: minutes += int(tl.actual_minutes)
    used_hours = round(minutes/60.0, 2)
    run_map: Dict[int, str] = {}
    for t in tasks:
        tl = db.query(TimeLog).filter(TimeLog.task_id==t.id, TimeLog.staff_id==s.id, TimeLog.ended_at==None).order_by(TimeLog.id.desc()).first()
        if tl:
            run_map[t.id] = tl.started_at
    warn_limit = used_hours > float(s.max_hours_per_month or 0)
    lang = detect_language(request)
    trans = get_translations(lang)
    return templates.TemplateResponse("cleaner.html", {"request": request, "tasks": tasks, "used_hours": used_hours, "apt_map": apt_map, "book_map": book_map, "booking_details_map": booking_details_map, "staff": s, "show_done": show_done, "run_map": run_map, "warn_limit": warn_limit, "lang": lang, "t": trans})

@app.post("/cleaner/{token}/start")
async def cleaner_start(token: str, task_id: int = Form(...), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t: raise HTTPException(status_code=404, detail="Task nicht gefunden")
    
    # Beende alle offenen TimeLogs dieses Staff
    open_tls = db.query(TimeLog).filter(TimeLog.staff_id==s.id, TimeLog.ended_at==None).all()
    for open_tl in open_tls:
        from datetime import datetime
        open_tl.ended_at = now_iso()
        fmt = "%Y-%m-%d %H:%M:%S"
        try:
            start = datetime.strptime(open_tl.started_at, fmt)
            end = datetime.strptime(open_tl.ended_at, fmt)
            open_tl.actual_minutes = int((end-start).total_seconds()//60)
        except Exception:
            pass
    
    # Erstelle neues TimeLog für diesen Task
    new_tl = TimeLog(task_id=task_id, staff_id=s.id, started_at=now_iso(), ended_at=None, actual_minutes=None)
    t.status = "running"
    db.add(new_tl)
    db.commit()
    return RedirectResponse(url=f"/cleaner/{token}", status_code=303)

@app.post("/cleaner/{token}/stop")
async def cleaner_stop(token: str, task_id: int = Form(...), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t: raise HTTPException(status_code=404, detail="Task nicht gefunden")
    
    tl = db.query(TimeLog).filter(TimeLog.task_id==task_id, TimeLog.staff_id==s.id, TimeLog.ended_at==None).order_by(TimeLog.id.desc()).first()
    if tl:
        from datetime import datetime
        fmt = "%Y-%m-%d %H:%M:%S"
        tl.ended_at = now_iso()
        try:
            start = datetime.strptime(tl.started_at, fmt)
            end = datetime.strptime(tl.ended_at, fmt)
            tl.actual_minutes = int((end-start).total_seconds()//60)
        except Exception:
            pass
    
    t.status = "open"
    db.commit()
    return RedirectResponse(url=f"/cleaner/{token}", status_code=303)

@app.post("/cleaner/{token}/done")
async def cleaner_done(token: str, task_id: int = Form(...), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t: raise HTTPException(status_code=404, detail="Task nicht gefunden")
    
    # Beende TimeLog wenn noch offen
    tl = db.query(TimeLog).filter(TimeLog.task_id==task_id, TimeLog.staff_id==s.id, TimeLog.ended_at==None).order_by(TimeLog.id.desc()).first()
    if tl:
        from datetime import datetime
        fmt = "%Y-%m-%d %H:%M:%S"
        tl.ended_at = now_iso()
        try:
            start = datetime.strptime(tl.started_at, fmt)
            end = datetime.strptime(tl.ended_at, fmt)
            tl.actual_minutes = int((end-start).total_seconds()//60)
        except Exception:
            pass
    
    t.status = "done"
    db.commit()
    return RedirectResponse(url=f"/cleaner/{token}", status_code=303)

@app.post("/cleaner/{token}/reopen")
async def cleaner_reopen(token: str, task_id: int = Form(...), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    tl = db.query(TimeLog).filter(TimeLog.task_id==task_id, TimeLog.staff_id==s.id).order_by(TimeLog.id.desc()).first()
    if tl:
        db.delete(tl)
    t.status = "open"
    db.commit()
    return RedirectResponse(url=f"/cleaner/{token}?show_done=1", status_code=303)

@app.post("/cleaner/{token}/note")
async def cleaner_note(token: str, task_id: int = Form(...), note: str = Form(""), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    t.notes = (note or "").strip()
    db.commit()
    return JSONResponse({"ok": True, "task_id": t.id, "note": t.notes})
