
import os, json, datetime as dt, csv, io, logging
from typing import List
from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from .db import init_db, SessionLocal
from .models import Booking, Staff, Apartment, Task, TimeLog
from .services_smoobu import SmoobuClient
from .utils import new_token, today_iso, now_iso
from .sync import upsert_tasks_from_bookings

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Berlin")
REFRESH_INTERVAL_MINUTES = int(os.getenv("REFRESH_INTERVAL_MINUTES", "60"))

log = logging.getLogger("smoobu")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Smoobu Staff Planner Pro (v5)")
app.mount("/static", StaticFiles(directory="static") if os.path.isdir("static") else StaticFiles(directory="."), name="static")
templates = Jinja2Templates(directory="app/templates")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.on_event("startup")
async def startup_event():
    init_db()
    # ensure admin token
    if not ADMIN_TOKEN:
        log.warning("ADMIN_TOKEN not set! Admin UI will be inaccessible.")
    # initial import
    try:
        await refresh_bookings_job()
    except Exception as e:
        log.exception("Initial import failed: %s", e)
    # scheduler
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(refresh_bookings_job, IntervalTrigger(minutes=REFRESH_INTERVAL_MINUTES))
    scheduler.start()

def _daterange(days=60):
    start = dt.date.today()
    end = start + dt.timedelta(days=days)
    return start.isoformat(), end.isoformat()

async def refresh_bookings_job():
    client = SmoobuClient()
    start, end = _daterange(60)
    log.info("Refreshing bookings from %s to %s", start, end)
    items = client.get_reservations(start, end)
    log.info("Fetched %d bookings", len(items))
    with SessionLocal() as db:
        # upsert apartments and bookings
        seen_booking_ids: List[int] = []
        seen_apartment_ids: List[int] = []
        for it in items:
            b_id = int(it.get("id"))
            apt = it.get("apartment") or {}
            apt_id = int(apt.get("id")) if apt.get("id") is not None else None
            apt_name = apt.get("name") or ""
            # Apartment
            if apt_id is not None and apt_id not in seen_apartment_ids:
                a = db.get(Apartment, apt_id)
                if not a:
                    a = Apartment(id=apt_id, name=apt_name, planned_minutes=90, active=True)
                    db.add(a)
                else:
                    a.name = apt_name or a.name
                seen_apartment_ids.append(apt_id)
            # Booking
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
            seen_booking_ids.append(b_id)

        # remove vanished bookings
        existing_ids = [row[0] for row in db.query(Booking.id).all()]
        for bid in existing_ids:
            if bid not in seen_booking_ids:
                db.delete(db.get(Booking, bid))

        db.commit()

        # Build/Upsert tasks (keine Überschreibung manueller Felder)
        bookings = db.query(Booking).all()
        upsert_tasks_from_bookings(bookings)

@app.get("/health")
async def health():
    return {"ok": True, "time": now_iso()}

# -------------------- Admin UI --------------------

@app.get("/admin/{token}")
async def admin_home(request: Request, token: str, db=Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403)
    tasks = db.query(Task).order_by(Task.date, Task.id).all()
    staff = db.query(Staff).filter(Staff.active==True).all()
    apts = db.query(Apartment).filter(Apartment.active==True).all()
    return templates.TemplateResponse("admin_home.html", {"request": request, "token": token, "tasks": tasks, "staff": staff, "apartments": apts})

@app.get("/admin/{token}/staff")
async def admin_staff(request: Request, token: str, db=Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403)
    staff = db.query(Staff).order_by(Staff.name).all()
    return templates.TemplateResponse("admin_staff.html", {"request": request, "token": token, "staff": staff})

@app.post("/admin/{token}/staff/add")
async def admin_staff_add(token: str, name: str = Form(...), hourly_rate: float = Form(0.0), db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    s = Staff(name=name, hourly_rate=hourly_rate, magic_token=new_token(16), active=True)
    db.add(s); db.commit()
    return RedirectResponse(url=f"/admin/{token}/staff", status_code=303)

@app.post("/admin/{token}/staff/toggle")
async def admin_staff_toggle(token: str, staff_id: int = Form(...), db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    s = db.get(Staff, staff_id); s.active = not s.active; db.commit()
    return RedirectResponse(url=f"/admin/{token}/staff", status_code=303)

@app.post("/admin/{token}/task/assign")
async def admin_task_assign(token: str, task_id: int = Form(...), staff_id: int = Form(None), db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    t = db.get(Task, task_id); t.assigned_staff_id = staff_id if staff_id else None; db.commit()
    return RedirectResponse(url=f"/admin/{token}", status_code=303)

@app.post("/admin/{token}/task/lock")
async def admin_task_lock(token: str, task_id: int = Form(...), lock: int = Form(1), db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    t = db.get(Task, task_id); t.locked = bool(int(lock)); db.commit()
    return RedirectResponse(url=f"/admin/{token}", status_code=303)

@app.get("/admin/{token}/apartments")
async def admin_apartments(request: Request, token: str, db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    apts = db.query(Apartment).order_by(Apartment.name).all()
    return templates.TemplateResponse("admin_apartments.html", {"request": request, "token": token, "apartments": apts})

@app.post("/admin/{token}/apartments/update")
async def admin_apartments_update(token: str, apartment_id: int = Form(...), planned_minutes: int = Form(...), db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    a = db.get(Apartment, apartment_id); a.planned_minutes = int(planned_minutes); db.commit()
    return RedirectResponse(url=f"/admin/{token}/apartments", status_code=303)

@app.get("/admin/{token}/import")
async def admin_import(token: str):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    await refresh_bookings_job()
    return PlainTextResponse("Import done.")

@app.get("/admin/{token}/export")
async def admin_export(token: str, month: str, db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    # month: YYYY-MM
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
    output = io.StringIO()
    w = csv.DictWriter(output, fieldnames=list(rows[0].keys()) if rows else ["date"])
    w.writeheader()
    for r in rows: w.writerow(r)
    return StreamingResponse(iter([output.getvalue().encode("utf-8")]), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=report-{month}.csv"})

# -------------------- Cleaner --------------------

@app.get("/cleaner/{token}")
async def cleaner_home(request: Request, token: str, db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    tasks = db.query(Task).filter(Task.assigned_staff_id==s.id).order_by(Task.date, Task.id).all()
    # used hours this month
    month = dt.date.today().strftime("%Y-%m")
    minutes = 0
    logs = db.query(TimeLog).filter(TimeLog.staff_id==s.id, TimeLog.actual_minutes!=None).all()
    for tl in logs:
        if tl.started_at[:7]==month and tl.actual_minutes: minutes += int(tl.actual_minutes)
    used_hours = round(minutes/60.0, 2)
    return templates.TemplateResponse("cleaner.html", {"request": request, "tasks": tasks, "used_hours": used_hours})

@app.post("/cleaner/{token}/start")
async def cleaner_start(token: str, task_id: int = Form(...), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    # stop any open timelog for this staff
    open_tl = db.query(TimeLog).filter(TimeLog.staff_id==s.id, TimeLog.ended_at==None).first()
    if open_tl:
        open_tl.ended_at = now_iso()
        from datetime import datetime
        fmt = "%Y-%m-%d %H:%M:%S"
        open_tl.actual_minutes = int((datetime.strptime(open_tl.ended_at, fmt)-datetime.strptime(open_tl.started_at, fmt)).total_seconds()//60)
        db.commit()
    # start new
    tl = TimeLog(task_id=task_id, staff_id=s.id, started_at=now_iso(), ended_at=None, actual_minutes=None)
    db.add(tl); db.commit()
    return RedirectResponse(url=f"/cleaner/{token}", status_code=303)

@app.post("/cleaner/{token}/stop")
async def cleaner_stop(token: str, task_id: int = Form(...), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    tl = db.query(TimeLog).filter(TimeLog.task_id==task_id, TimeLog.staff_id==s.id, TimeLog.ended_at==None).first()
    if not tl: raise HTTPException(status_code=404)
    from datetime import datetime
    fmt = "%Y-%m-%d %H:%M:%S"
    tl.ended_at = now_iso()
    start = datetime.strptime(tl.started_at, fmt)
    end = datetime.strptime(tl.ended_at, fmt)
    tl.actual_minutes = int((end-start).total_seconds()//60)
    db.commit()
    return RedirectResponse(url=f"/cleaner/{token}", status_code=303)
