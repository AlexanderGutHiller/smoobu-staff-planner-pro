
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
from .utils import new_token, today_iso, now_iso, pick_lang

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
DEFAULT_TASK_START = (os.getenv("DEFAULT_TASK_START", "") or "11:00").strip()

log = logging.getLogger("smoobu")
log.setLevel(logging.INFO)

app = FastAPI(title="Smoobu Staff Planner Pro")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

import json as _json
templates.env.filters["loads"] = lambda s: _json.loads(s) if s else {}

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _is_confirmed(res: dict) -> bool:
    status = (res.get("status") or res.get("bookingStatus") or "").lower()
    rtype = (res.get("type") or res.get("reservationType") or "").lower()
    bad_status = {"cancelled","canceled","inquiry","enquiry","tentative","blocked","block","owner","ownerstay","maintenance"}
    if status in bad_status or rtype in bad_status:
        return False
    if res.get("isBlocked") or res.get("blocked"):
        return False
    return True

@app.on_event("startup")
async def startup_event():
    init_db()
    interval_min = int(os.getenv("REFRESH_INTERVAL_MINUTES", "60"))
    scheduler = AsyncIOScheduler(timezone=os.getenv("TIMEZONE", "Europe/Berlin"))
    scheduler.add_job(refresh_bookings_job, IntervalTrigger(minutes=interval_min))
    scheduler.start()
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
    reservations = await client.get_bookings(start.isoformat(), end.isoformat())
    reservations = [r for r in reservations if _is_confirmed(r)]
    db = SessionLocal()
    try:
        apt_cache = {a.name: a for a in db.query(Apartment).all()}
        existing_ids = {b.id for b in db.query(Booking).all()}
        seen_ids = set()

        for r in reservations:
            bid = r.get("id") or r.get("bookingId") or r.get("reservationId")
            if bid is None:
                continue
            seen_ids.add(bid)
            apt = (r.get("apartment") or {})
            apt_name = (apt.get("name") or r.get("apartmentName") or "").strip()
            apt_id_smoobu = apt.get("id") or r.get("apartmentId")

            ap = None
            if apt_name:
                ap = apt_cache.get(apt_name)
                if ap is None:
                    ap = Apartment(name=apt_name, smoobu_id=apt_id_smoobu or None, planned_minutes=90)
                    db.add(ap); db.flush()
                    apt_cache[apt_name] = ap

            bk = db.query(Booking).filter(Booking.id == bid).first()
            if not bk:
                bk = Booking(id=bid)
            bk.apartment_id = ap.id if ap else None
            bk.apartment_name = apt_name or ""
            bk.arrival = (r.get("arrival") or r.get("checkIn") or "")[:10]
            bk.departure = (r.get("departure") or r.get("checkOut") or "")[:10]
            bk.nights = int(r.get("nights") or 0)
            bk.adults = int(r.get("adults") or r.get("numberOfGuests") or 1)
            bk.children = int(r.get("children") or 0)
            bk.guest_comments = (r.get("notice") or r.get("guestComments") or r.get("comment") or "")[:2000]
            bk.status = (r.get("status") or r.get("bookingStatus") or "confirmed")
            db.merge(bk)

        for old in existing_ids - seen_ids:
            db.query(Booking).filter(Booking.id == old).delete()
        db.commit()

        today_iso_s = dt.date.today().isoformat()
        end_iso_s = end.isoformat()
        seen_task_booking_ids = set()
        for bk in db.query(Booking).all():
            if not bk.departure or not (today_iso_s <= bk.departure <= end_iso_s):
                continue
            ap = apt_cache.get(bk.apartment_name) or db.query(Apartment).filter(Apartment.name == bk.apartment_name).first()
            planned = ap.planned_minutes if ap else 90

            t = db.query(Task).filter(Task.booking_id == bk.id).first()
            if t:
                t.date = bk.departure
                t.apartment_id = ap.id if ap else None
                t.planned_minutes = planned
                if not t.start_time:
                    t.start_time = DEFAULT_TASK_START
            else:
                t = Task(
                    date=bk.departure,
                    start_time=DEFAULT_TASK_START,
                    planned_minutes=planned,
                    apartment_id=ap.id if ap else None,
                    booking_id=bk.id,
                    status="open",
                    extras_json="{}"
                )
                db.add(t)
            seen_task_booking_ids.add(bk.id)

        for t in db.query(Task).filter(Task.date >= today_iso_s).all():
            if t.booking_id and t.booking_id not in seen_task_booking_ids:
                db.delete(t)

        db.commit()
        log.info("Smoobu import finished: %d bookings, %d tasks", len(reservations), db.query(Task).count())
    finally:
        db.close()

def ensure_admin(token: str):
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid admin token")

def i18n(request: Request):
    from .utils import pick_lang
    lang = pick_lang(request.headers.get("accept-language"))
    T = {
        "de": {"title_admin":"Einsätze","title_cleaner":"Meine Einsätze","team":"Team","apartments":"Apartments","csv_export":"CSV Export","import_now":"Jetzt importieren","date":"Datum","start":"Start","apartment":"Apartment","planned":"Geplant (Min)","extras":"Extras","note":"Notiz","staff":"Staff","status":"Status","action":"Aktion","open":"offen","done":"fertig","save":"Speichern","next_guests":"Gäste (nächste)","adults_short":"Erw.","children_short":"Ki.","keep_link":"Diesen Link nicht weitergeben.","month_hours":"Aktueller Monat:","hours":"Std erfasst.","timer":"Timer","start_btn":"Start","stop_btn":"Stop","timer_hint":"Hinweis: Timer läuft weiter, solange die Seite offen ist.","crib":"Zustellbett","highchair":"Kinderstuhl"},
        "en": {"title_admin":"Assignments","title_cleaner":"My Assignments","team":"Team","apartments":"Apartments","csv_export":"CSV Export","import_now":"Import now","date":"Date","start":"Start","apartment":"Apartment","planned":"Planned (min)","extras":"Extras","note":"Note","staff":"Staff","status":"Status","action":"Action","open":"open","done":"done","save":"Save","next_guests":"Next guests","adults_short":"Adults","children_short":"Kids","keep_link":"Do not share this link.","month_hours":"Current month:","hours":"hrs recorded.","timer":"Timer","start_btn":"Start","stop_btn":"Stop","timer_hint":"Tip: Timer keeps running while this page stays open.","crib":"Extra bed","highchair":"High chair"},
        "bg": {"title_admin":"Задачи","title_cleaner":"Моите задачи","team":"Екип","apartments":"Апартаменти","csv_export":"CSV експорт","import_now":"Импортиране","date":"Дата","start":"Старт","apartment":"Апартамент","planned":"Планирано (мин)","extras":"Екстри","note":"Бележка","staff":"Служители","status":"Статус","action":"Действие","open":"отворена","done":"готово","save":"Запази","next_guests":"Следв. гости","adults_short":"Възр.","children_short":"Деца","keep_link":"Не споделяйте този линк.","month_hours":"Текущ месец:","hours":"ч. отчетени.","timer":"Таймер","start_btn":"Старт","stop_btn":"Стоп","timer_hint":"Съвет: Таймерът продължава, докато страницата е отворена.","crib":"Допълнително легло","highchair":"Детско столче"},
        "ro": {"title_admin":"Sarcini","title_cleaner":"Sarcinile mele","team":"Echipă","apartments":"Apartamente","csv_export":"Export CSV","import_now":"Importă acum","date":"Data","start":"Start","apartment":"Apartament","planned":"Planificat (min)","extras":"Extra","note":"Notă","staff":"Personal","status":"Status","action":"Acțiune","open":"deschis","done":"finalizat","save":"Salvează","next_guests":"Următorii oaspeți","adults_short":"Adulți","children_short":"Copii","keep_link":"Nu partajați acest link.","month_hours":"Luna curentă:","hours":"ore înregistrate.","timer":"Cronometru","start_btn":"Start","stop_btn":"Stop","timer_hint":"Sugestie: cronometrul continuă cât timp pagina rămâne deschisă.","crib":"Pat suplimentar","highchair":"Scaun înalt"},
        "ru": {"title_admin":"Задачи","title_cleaner":"Мои задачи","team":"Команда","apartments":"Апартаменты","csv_export":"Экспорт CSV","import_now":"Импорт","date":"Дата","start":"Начало","apartment":"Апартаменты","planned":"План (мин)","extras":"Дополнительно","note":"Заметка","staff":"Персонал","status":"Статус","action":"Действие","open":"открыто","done":"готово","save":"Сохранить","next_guests":"Следующие гости","adults_short":"Взр.","children_short":"Дети","keep_link":"Не делитесь этой ссылкой.","month_hours":"Текущий месяц:","hours":"ч. учтено.","timer":"Таймер","start_btn":"Старт","stop_btn":"Стоп","timer_hint":"Подсказка: таймер работает, пока страница открыта.","crib":"Доп. кровать","highchair":"Детский стул"}
    }
    return T.get(lang, T["en"])

@app.get("/admin/{token}")
async def admin_home(token: str, request: Request, db=Depends(get_db)):
    ensure_admin(token)
    today = today_iso()
    tasks = db.query(Task).order_by(Task.date, Task.id).all()
    staff = db.query(Staff).filter(Staff.active==True).order_by(Staff.name).all()
    apts  = db.query(Apartment).order_by(Apartment.name).all()

    next_by_apartment = {}
    for bk in db.query(Booking).all():
        if bk.arrival and bk.apartment_id:
            m = next_by_apartment.setdefault(bk.apartment_id, {})
            current = m.get(bk.arrival)
            if not current or (bk.adults + bk.children) > (current.adults + current.children):
                m[bk.arrival] = bk

    return templates.TemplateResponse("admin_home.html", {
        "request": request, "token": token, "tasks": tasks, "staff": staff, "apts": apts, "today": today,
        "next_by_apartment": next_by_apartment, "T": i18n(request)
    })

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
    apartment_id: str | None = Form(None),
    assigned_staff_id: str | None = Form(None),
    notes: str = Form(""),
    crib: int = Form(0),
    highchair: int = Form(0),
    extra_text: str = Form(""),
    db=Depends(get_db)
):
    ensure_admin(token)
    def _to_int_or_none(v):
        if v is None: return None
        v = str(v).strip()
        return int(v) if v.isdigit() else None

    t = db.query(Task).filter(Task.id==task_id).first()
    if t:
        t.date = date
        t.start_time = (start_time or "").strip() or None
        t.planned_minutes = planned_minutes
        t.apartment_id = _to_int_or_none(apartment_id)
        t.assigned_staff_id = _to_int_or_none(assigned_staff_id)
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
    from .utils import pick_lang
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

    open_logs = {}
    for t in tasks:
        tl = db.query(TimeLog).filter(TimeLog.task_id==t.id, TimeLog.staff_id==s.id, TimeLog.ended_at==None).order_by(TimeLog.id.desc()).first()
        if tl:
            open_logs[t.id] = tl.started_at

    next_by_apartment = {}
    for bk in db.query(Booking).all():
        if bk.arrival and bk.apartment_id:
            m = next_by_apartment.setdefault(bk.apartment_id, {})
            current = m.get(bk.arrival)
            if not current or (bk.adults + bk.children) > (current.adults + current.children):
                m[bk.arrival] = bk

    def i18n(request):
        lang = pick_lang(request.headers.get("accept-language"))
        T = {
            "de": {"title_cleaner":"Meine Einsätze","date":"Datum","start":"Start","apartment":"Apartment","planned":"Geplant (Min)","next_guests":"Nächste Gäste","extras":"Extras","note":"Notiz","timer":"Timer","start_btn":"Start","stop_btn":"Stop","keep_link":"Diesen Link nicht weitergeben.","month_hours":"Aktueller Monat:","hours":"Std erfasst.","adults_short":"Erw.","children_short":"Ki.","crib":"Zustellbett","highchair":"Kinderstuhl","timer_hint":"Hinweis: Timer läuft weiter, solange die Seite offen ist."},
            "en": {"title_cleaner":"My Assignments","date":"Date","start":"Start","apartment":"Apartment","planned":"Planned (min)","next_guests":"Next guests","extras":"Extras","note":"Note","timer":"Timer","start_btn":"Start","stop_btn":"Stop","keep_link":"Do not share this link.","month_hours":"Current month:","hours":"hrs recorded.","adults_short":"Adults","children_short":"Kids","crib":"Extra bed","highchair":"High chair","timer_hint":"Tip: Timer keeps running while this page stays open."},
            "bg": {"title_cleaner":"Моите задачи","date":"Дата","start":"Старт","apartment":"Апартамент","planned":"Планирано (мин)","next_guests":"Следв. гости","extras":"Екстри","note":"Бележка","timer":"Таймер","start_btn":"Старт","stop_btn":"Стоп","keep_link":"Не споделяйте този линк.","month_hours":"Текущ месец:","hours":"ч. отчетени.","adults_short":"Възр.","children_short":"Деца","crib":"Допълнително легло","highchair":"Детско столче","timer_hint":"Съвет: Таймерът продължава, докато страницата е отворена."},
            "ro": {"title_cleaner":"Sarcinile mele","date":"Data","start":"Start","apartment":"Apartament","planned":"Planificat (min)","next_guests":"Următorii oaspeți","extras":"Extra","note":"Notă","timer":"Cronometru","start_btn":"Start","stop_btn":"Stop","keep_link":"Nu partajați acest link.","month_hours":"Luna curentă:","hours":"ore înregistrate.","adults_short":"Adulți","children_short":"Copii","crib":"Pat suplimentar","highchair":"Scaun înalt","timer_hint":"Sugestie: cronometrul continuă cât timp pagina rămâne deschisă."},
            "ru": {"title_cleaner":"Мои задачи","date":"Дата","start":"Начало","apartment":"Апартаменты","planned":"План (мин)","next_guests":"Следующие гости","extras":"Дополнительно","note":"Заметка","timer":"Таймер","start_btn":"Старт","stop_btn":"Стоп","keep_link":"Не делитесь этой ссылкой.","month_hours":"Текущий месяц:","hours":"ч. учтено.","adults_short":"Взр.","children_short":"Дети","crib":"Доп. кровать","highchair":"Детский стул","timer_hint":"Подсказка: таймер работает, пока страница открыта."}
        }
        return T.get(lang, T["en"])
    T = i18n(request)

    return templates.TemplateResponse("cleaner.html", {"request": request, "staff": s, "tasks": tasks, "apts": apts, "used_hours": used_hours, "open_logs": open_logs, "next_by_apartment": next_by_apartment, "T": T})
