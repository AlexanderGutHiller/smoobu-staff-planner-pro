
import os, json, datetime as dt, csv, io, logging
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

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

log = logging.getLogger("smoobu")
log.setLevel(logging.INFO)

app = FastAPI(title="Smoobu Staff Planner Pro")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Jinja filter 'loads'
import json as _json
templates.env.filters["loads"] = lambda s: _json.loads(s) if s else {}

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.on_event("startup")
async def startup_event():
    init_db()
    interval_min = int(os.getenv("REFRESH_INTERVAL_MINUTES", "60"))
    scheduler = AsyncIOScheduler(timezone=os.getenv("TIMEZONE", "Europe/Berlin"))
    scheduler.add_job(refresh_bookings_job, IntervalTrigger(minutes=interval_min))
    scheduler.start()
    # Immediate import on boot
    log.info("Initial import on startup")
    await refresh_bookings_job()

@app.get("/")
async def root():
    return PlainTextResponse("OK - use /admin/<ADMIN_TOKEN>")

async def refresh_bookings_job():
    start = dt.date.today()
    end = start + dt.timedelta(days=60)
    client = SmoobuClient()
    log.info("Smoobu import: %s -> %s", start, end)
    bookings = await client.get_bookings(start.isoformat(), end.isoformat())
    db = SessionLocal()
    try:
        existing = {b.id for b in db.query(Booking).all()}
        seen = set()
        for b in bookings:
            bid = b.get("id")
            if bid is None:
                continue
            seen.add(bid)
            apt = (b.get("apartment") or {})
            bk = db.query(Booking).filter(Booking.id == bid).first() or Booking(id=bid)
            bk.apartment_id = apt.get("id")
            bk.apartment_name = apt.get("name","")
            bk.arrival = (b.get("arrival") or "")[:10]
            bk.departure = (b.get("departure") or "")[:10]
            bk.nights = int(b.get("nights") or 0)
            bk.adults = int(b.get("adults") or 1)
            bk.children = int(b.get("children") or 0)
            bk.guest_comments = (b.get("notice") or "")[:2000]
            db.merge(bk)
            if bk.apartment_name:
                ap = db.query(Apartment).filter(Apartment.name == bk.apartment_name).first()
                if not ap:
                    ap = Apartment(name=bk.apartment_name, smoobu_id=bk.apartment_id or None, planned_minutes=90)
                    db.add(ap)
        for old in existing - seen:
            db.query(Booking).filter(Booking.id == old).delete()
        db.commit()
        today = dt.date.today().isoformat()
        db.query(Task).filter(Task.date >= today).delete()
        for bk in db.query(Booking).all():
            if not bk.departure:
                continue
            ap = db.query(Apartment).filter(Apartment.name == bk.apartment_name).first()
            planned = ap.planned_minutes if ap else 90
            t = Task(date=bk.departure, planned_minutes=planned, apartment_id=ap.id if ap else None,
                     booking_id=bk.id, status="open", extras_json="{}")
            db.add(t)
        db.commit()
        log.info("Smoobu import finished: %d bookings, %d tasks", len(bookings), db.query(Task).count())
    finally:
        db.close()

def ensure_admin(token: str):
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid admin token")

@app.get("/admin/{token}")
async def admin_home(token: str, request: Request, db=Depends(get_db)):
    ensure_admin(token)
    today = today_iso()
    tasks = db.query(Task).order_by(Task.date, Task.id).all()
    staff = db.query(Staff).filter(Staff.active==True).order_by(Staff.name).all()
    apts  = db.query(Apartment).order_by(Apartment.name).all()
    return templates.TemplateResponse("admin_home.html", {"request": request, "token": token, "tasks": tasks, "staff": staff, "apts": apts, "today": today})

@app.get("/admin/{token}/import")
async def admin_import_now(token: str):
    ensure_admin(token)
    await refresh_bookings_job()
    return RedirectResponse(url=f"/admin/{token}", status_code=303)

@app.post("/admin/{token}/task/update")
async def admin_task_update(token: str,
    task_id: int = Form(...),
    date: str = Form(...),
    start_time: str | None = Form(None),
    planned_minutes: int = Form(90),
    apartment_id: int | None = Form(None),
    assigned_staff_id: int | None = Form(None),
    notes: str = Form(""),
    crib: int = Form(0),
    highchair: int = Form(0),
    extra_text: str = Form(""),
    db=Depends(get_db)
):
    ensure_admin(token)
    t = db.query(Task).filter(Task.id==task_id).first()
    if t:
        t.date = date
        t.start_time = start_time or None
        t.planned_minutes = planned_minutes
        t.apartment_id = apartment_id or None
        t.assigned_staff_id = assigned_staff_id or None
        extras = {"crib": bool(crib), "highchair": bool(highchair), "text": extra_text}
        t.extras_json = json.dumps(extras, ensure_ascii=False)
        t.notes = notes
        db.commit()
    return RedirectResponse(url=f"/admin/{token}", status_code=303)

@app.post("/admin/{token}/task/status")
async def admin_task_status(token: str, task_id: int = Form(...), status: str = Form(...), db=Depends(get_db)):
    ensure_admin(token)
    t = db.query(Task).filter(Task.id==task_id).first()
    if t:
        t.status = status
        db.commit()
    return RedirectResponse(url=f"/admin/{token}", status_code=303)

@app.get("/admin/{token}/staff")
async def admin_staff(token: str, request: Request, db=Depends(get_db)):
    ensure_admin(token)
    staff = db.query(Staff).order_by(Staff.name).all()
    return templates.TemplateResponse("admin_staff.html", {"request": request, "token": token, "staff": staff})

@app.post("/admin/{token}/staff/add")
async def admin_staff_add(token: str, name: str = Form(...), hourly_rate: float = Form(15.0), max_hours_month: float = Form(160.0), db=Depends(get_db)):
    ensure_admin(token)
    s = Staff(name=name, hourly_rate=hourly_rate, max_hours_month=max_hours_month, active=True, magic_token=new_token())
    db.add(s); db.commit()
    return RedirectResponse(url=f"/admin/{token}/staff", status_code=303)

@app.post("/admin/{token}/staff/update")
async def admin_staff_update(token: str, staff_id: int = Form(...), hourly_rate: float = Form(15.0), max_hours_month: float = Form(160.0), active: int = Form(1), regen_token: int = Form(0), db=Depends(get_db)):
    ensure_admin(token)
    s = db.query(Staff).filter(Staff.id==staff_id).first()
    if s:
        s.hourly_rate = hourly_rate
        s.max_hours_month = max_hours_month
        s.active = bool(active)
        if regen_token:
            s.magic_token = new_token()
        db.commit()
    return RedirectResponse(url=f"/admin/{token}/staff", status_code=303)

@app.get("/admin/{token}/apartments")
async def admin_apartments(token: str, request: Request, db=Depends(get_db)):
    ensure_admin(token)
    apts = db.query(Apartment).order_by(Apartment.name).all()
    return templates.TemplateResponse("admin_apartments.html", {"request": request, "token": token, "apts": apts})

@app.post("/admin/{token}/apartments/update")
async def admin_apartments_update(token: str, apartment_id: int = Form(...), planned_minutes: int = Form(90), db=Depends(get_db)):
    ensure_admin(token)
    ap = db.query(Apartment).filter(Apartment.id==apartment_id).first()
    if ap:
        ap.planned_minutes = planned_minutes
        db.commit()
    return RedirectResponse(url=f"/admin/{token}/apartments", status_code=303)

@app.get("/admin/{token}/export")
async def admin_export(token: str, month: str, db=Depends(get_db)):
    ensure_admin(token)
    start = dt.date.fromisoformat(month + "-01")
    end = dt.date(start.year + (start.month==12), (start.month%12)+1, 1)
    tasks = db.query(Task).filter(Task.date >= start.isoformat(), Task.date < end.isoformat()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date","apartment","staff","planned_minutes","actual_minutes","hourly_rate","cost_eur","notes","extras"])
    for t in tasks:
        staff = db.query(Staff).filter(Staff.id==t.assigned_staff_id).first() if t.assigned_staff_id else None
        apt = db.query(Apartment).filter(Apartment.id==t.apartment_id).first() if t.apartment_id else None
        tl = db.query(TimeLog).filter(TimeLog.task_id==t.id).order_by(TimeLog.id.desc()).first()
        actual = tl.actual_minutes if tl and tl.actual_minutes is not None else None
        rate = staff.hourly_rate if staff else 0.0
        cost = round((actual or 0)/60*rate, 2) if actual is not None else ""
        writer.writerow([t.date, apt.name if apt else "", staff.name if staff else "",
                         t.planned_minutes, actual if actual is not None else "",
                         rate if staff else "", cost, t.notes, t.extras_json])
    output.seek(0)
    return StreamingResponse(iter([output.read().encode("utf-8")]), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=export_{month}.csv"})

@app.get("/cleaner/{token}")
async def cleaner_home(token: str, request: Request, db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403, detail="Invalid token")
    tasks = db.query(Task).filter(Task.assigned_staff_id==s.id).order_by(Task.date, Task.id).all()
    apts = {a.id:a for a in db.query(Apartment).all()}
    today = dt.date.today()
    m_start = today.replace(day=1).isoformat()
    if today.month==12:
        m_end = dt.date(today.year+1,1,1).isoformat()
    else:
        m_end = dt.date(today.year, today.month+1,1).isoformat()
    minutes = 0
    for tl in db.query(TimeLog).all():
        if tl.staff_id==s.id and tl.started_at[:10] >= m_start and tl.started_at[:10] < m_end and tl.actual_minutes:
            minutes += tl.actual_minutes
    used_hours = round(minutes/60,2)
    return templates.TemplateResponse("cleaner.html", {"request": request, "staff": s, "tasks": tasks, "apts": apts, "used_hours": used_hours})

@app.post("/cleaner/{token}/start")
async def cleaner_start(token: str, task_id: int = Form(...), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.query(Task).filter(Task.id==task_id, Task.assigned_staff_id==s.id).first()
    if not t: raise HTTPException(status_code=404)
    open_log = db.query(TimeLog).filter(TimeLog.task_id==t.id, TimeLog.staff_id==s.id, TimeLog.ended_at==None).first()
    if not open_log:
        tl = TimeLog(task_id=t.id, staff_id=s.id, started_at=now_iso(), ended_at=None, actual_minutes=None)
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
