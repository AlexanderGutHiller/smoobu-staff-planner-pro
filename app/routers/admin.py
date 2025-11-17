"""Admin routes"""
import json
import io
import csv
import datetime as dt
import logging
from typing import Optional, Dict
from fastapi import APIRouter, Request, Depends, Form, HTTPException, Query
from fastapi.responses import RedirectResponse, StreamingResponse, PlainTextResponse, HTMLResponse, JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..dependencies import get_db, _is_admin_token
from ..helpers import detect_language, get_translations
from ..shared import templates
from ..config import BASE_URL, ADMIN_TOKEN, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM
from ..models import Booking, Staff, Apartment, Task, TimeLog, TaskSeries
from ..utils import new_token, today_iso, now_iso
from ..jobs import send_assignment_emails_job, send_whatsapp_for_existing_assignments, refresh_bookings_job, expand_series_job
from ..main import log

router = APIRouter(prefix="/admin/{token}", tags=["admin"])



# Admin Routes

# GET 
@router.get("")
async def admin_home(
    request: Request,
    token: str,
    date_range: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    staff_id: Optional[str] = Query(None),
    apartment_id: Optional[str] = Query(None),
    show_done: Optional[str] = Query(None),
    show_open: Optional[str] = Query(None),
    assignment_open: Optional[str] = Query(None),
    db=Depends(get_db),
):
    if not _is_admin_token(token, db):
        raise HTTPException(status_code=403)
    
    lang = detect_language(request)
    trans = get_translations(lang)
    
    q = db.query(Task)
    # Datumsvoreinstellung / -filter
    # Unterscheide: kein date_range-Parameter (Standard: nächste 7 Tage)
    # vs. explizit "Alle" gewählt (date_range="" in Query -> keine Beschränkung)
    has_date_range_param = "date_range" in request.query_params
    default_date_filter = date_range or ""
    today = dt.date.today()
    if date_range and not (date_from or date_to):
        if date_range == "today":
            date_from = today.isoformat()
            date_to = today.isoformat()
        elif date_range == "week":
            start = today - dt.timedelta(days=today.weekday())
            end = start + dt.timedelta(days=6)
            date_from = start.isoformat()
            date_to = end.isoformat()
        elif date_range == "month":
            start = today.replace(day=1)
            if start.month == 12:
                next_month = start.replace(year=start.year + 1, month=1, day=1)
            else:
                next_month = start.replace(month=start.month + 1, day=1)
            end = next_month - dt.timedelta(days=1)
            date_from = start.isoformat()
            date_to = end.isoformat()
        elif date_range == "next7":
            date_from = today.isoformat()
            date_to = (today + dt.timedelta(days=7)).isoformat()
    if not date_from and not date_to:
        # Fallback, wenn gar nichts gesetzt und kein explizites "Alle":
        # Standard: nächste 7 Tage
        if not has_date_range_param:
            date_from = today.isoformat()
            date_to = (today + dt.timedelta(days=7)).isoformat()
            if not default_date_filter:
                default_date_filter = "next7"
    # Status-Filter robust aus Query-Params ableiten
    qp = request.query_params
    if "show_done" in qp:
        show_done_val = 1 if qp.get("show_done") == "1" else 0
    else:
        show_done_val = 1  # Standard: erledigte anzeigen
    if "show_open" in qp:
        show_open_val = 1 if qp.get("show_open") == "1" else 0
    else:
        show_open_val = 1  # Standard: offene anzeigen

    # Zuweisungs-Filter: "Zuweisung noch offen" (unassigned oder nicht accepted)
    if "assignment_open" in qp:
        assignment_open_val = qp.get("assignment_open") == "1"
    else:
        assignment_open_val = False

    # Staff- und Apartment-Filter robust aus Strings parsen ("" = kein Filter)
    staff_id_val: Optional[int] = None
    if staff_id and str(staff_id).strip():
        try:
            staff_id_val = int(staff_id)
        except ValueError:
            staff_id_val = None
    apartment_id_val: Optional[int] = None
    if apartment_id is not None and str(apartment_id).strip() != "":
        try:
            apartment_id_val = int(apartment_id)
        except ValueError:
            apartment_id_val = None

    if date_from:
        q = q.filter(Task.date >= date_from)
    if date_to:
        q = q.filter(Task.date <= date_to)
    if staff_id_val:
        q = q.filter(Task.assigned_staff_id == staff_id_val)
    if apartment_id_val is not None:
        if apartment_id_val == 0:
            q = q.filter(Task.apartment_id == None)  # manuelle Aufgaben
        elif apartment_id_val:
            q = q.filter(Task.apartment_id == apartment_id_val)
    # Filter nach Status: erledigte und/oder offene Aufgaben
    from sqlalchemy import or_
    status_filters = []
    if show_done_val:
        status_filters.append(Task.status == "done")
    if show_open_val:
        status_filters.append(Task.status != "done")
    if status_filters:
        q = q.filter(or_(*status_filters))
    else:
        # Wenn beide Filter deaktiviert sind, zeige nichts
        q = q.filter(Task.id == -1)  # Unmögliche Bedingung
    # Filter nach Zuweisung offen (optional)
    if assignment_open_val:
        q = q.filter(or_(Task.assigned_staff_id == None, Task.assignment_status != "accepted"))

    tasks = q.order_by(Task.date, Task.id).all()
    staff = db.query(Staff).filter(Staff.active==True).all()
    apts = db.query(Apartment).filter(Apartment.active==True).all()
    apt_map = {a.id: a.name for a in apts}
    bookings = db.query(Booking).all()
    book_map = {b.id: (b.guest_name or "").strip() for b in bookings if b.guest_name}
    booking_details_map = {b.id: {'adults': b.adults or 0, 'children': b.children or 0, 'guest_name': (b.guest_name or "").strip()} for b in bookings}
    # booking_map: indexiert nach apartment_id für die nächste Anreise
    # Erstelle ein Dictionary mit apartment_id als Key und Booking-Objekt als Value
    # Für jedes Apartment wird das nächste (früheste) Booking verwendet
    booking_map = {}
    for b in bookings:
        if b.apartment_id:
            # Berechne guests aus adults + children
            guests = (b.adults or 0) + (b.children or 0)
            # Erstelle ein dict-ähnliches Objekt für das Template
            booking_info = {
                'arrival_date': b.arrival,
                'adults': b.adults or 0,
                'children': b.children or 0,
                'guests': guests
            }
            # Wenn noch kein Booking für dieses Apartment oder dieses ist früher
            if b.apartment_id not in booking_map:
                booking_map[b.apartment_id] = booking_info
            elif b.arrival and booking_map[b.apartment_id].get('arrival_date') and b.arrival < booking_map[b.apartment_id]['arrival_date']:
                booking_map[b.apartment_id] = booking_info
    log.debug("📊 Created book_map with %d entries, %d have guest names, booking_map with %d entries", len(bookings), len([b for b in bookings if b.guest_name and b.guest_name.strip()]), len(booking_map))
    
    # Timelog-Daten und Zusatzinformationen für jedes Task
    timelog_map = {}
    extras_map: Dict[int, Dict[str, bool]] = {}
    for t in tasks:
        # Summiere alle TimeLogs für diesen Task (nicht nur den letzten)
        all_tls = db.query(TimeLog).filter(TimeLog.task_id==t.id).all()
        total_minutes = 0
        latest_tl = None
        for tl in all_tls:
            if tl.actual_minutes:
                total_minutes += tl.actual_minutes
            # Finde den neuesten TimeLog für started_at/ended_at
            if not latest_tl or (tl.id and latest_tl.id and tl.id > latest_tl.id):
                latest_tl = tl
        
        if latest_tl or total_minutes > 0:
            timelog_map[t.id] = {
                'actual_minutes': total_minutes if total_minutes > 0 else (latest_tl.actual_minutes if latest_tl and latest_tl.actual_minutes else None),
                'started_at': latest_tl.started_at if latest_tl else None,
                'ended_at': latest_tl.ended_at if latest_tl else None
            }
        try:
            extras_map[t.id] = json.loads(t.extras_json or "{}") or {}
        except Exception:
            extras_map[t.id] = {}
    
    base_url = BASE_URL.rstrip("/")
    if not base_url:
        base_url = f"{request.url.scheme}://{request.url.hostname}" + (f":{request.url.port}" if request.url.port else "")
    # Prüfe, ob der Token zu einem Admin-Staff gehört (für Switch-Link)
    token_staff = db.query(Staff).filter(Staff.magic_token==token, Staff.is_admin==True, Staff.active==True).first()
    # Wenn Token einem Staff entspricht, Switch-Button ermöglichen
    staff_self = db.query(Staff).filter(Staff.magic_token==token).first()
    return templates.TemplateResponse(
        "admin_home.html",
        {
            "request": request,
            "token": token,
            "tasks": tasks,
            "staff": staff,
            "apartments": apts,
            "apt_map": apt_map,
            "book_map": book_map,
            "booking_details_map": booking_details_map,
            "booking_map": booking_map,
            "timelog_map": timelog_map,
            "extras_map": extras_map,
            "base_url": base_url,
            "lang": lang,
            "trans": trans,
            "show_done": show_done_val,
            "show_open": show_open_val,
            "assignment_open": assignment_open_val,
            "default_date_filter": default_date_filter,
            "staff_self": staff_self,
            "staff_id": staff_id_val,
            "apartment_id": apartment_id_val,
        },
    )

# ---------- Task Series Admin ----------


# GET /series
@router.get("/series")
async def admin_series_list(request: Request, token: str, db=Depends(get_db)):
    if not _is_admin_token(token, db): raise HTTPException(status_code=403)
    series = db.query(TaskSeries).order_by(TaskSeries.active.desc(), TaskSeries.start_date.desc()).all()
    apts = {a.id: a.name for a in db.query(Apartment).all()}
    staff = db.query(Staff).order_by(Staff.name).all()
    lang = detect_language(request); trans = get_translations(lang)
    base_url = BASE_URL.rstrip("/") or (f"{request.url.scheme}://{request.url.hostname}" + (f":{request.url.port}" if request.url.port else ""))
    return templates.TemplateResponse("admin_series.html", {"request": request, "token": token, "series": series, "apartments": apts, "staff": staff, "base_url": base_url, "lang": lang, "trans": trans})



# POST /series/add
@router.post("/series/add")
async def admin_series_add(
    token: str,
    title: str = Form(...),
    description: str = Form(""),
    apartment_id_raw: str = Form(""),
    staff_id_raw: str = Form(""),
    planned_minutes: int = Form(60),
    start_date: str = Form(...),
    start_time: str = Form(""),
    frequency: str = Form(...),
    interval: int = Form(1),
    byweekday: str = Form(""),
    bymonthday: str = Form(""),
    end_date: str = Form(""),
    count: int | None = Form(None),
    db=Depends(get_db)
):
    if not _is_admin_token(token, db): raise HTTPException(status_code=403)
    apt_id = None
    if apartment_id_raw.strip():
        try:
            aid = int(apartment_id_raw)
            if aid > 0: apt_id = aid
        except Exception: pass
    staff_id = None
    if staff_id_raw.strip():
        try:
            sid = int(staff_id_raw)
            if sid > 0: staff_id = sid
        except Exception: pass
    s = TaskSeries(
        title=title.strip(),
        description=description.strip(),
        apartment_id=apt_id,
        staff_id=staff_id,
        planned_minutes=planned_minutes,
        start_date=start_date[:10],
        start_time=start_time[:5] if start_time else "",
        frequency=frequency,
        interval=max(1,int(interval or 1)),
        byweekday=byweekday.strip(),
        bymonthday=bymonthday.strip(),
        end_date=(end_date[:10] if end_date else None),
        count=(int(count) if (str(count).strip().isdigit()) else None),
        active=True,
        created_at=now_iso()
    )
    db.add(s); db.commit()
    # expand immediately a bit
    expand_series_job(days_ahead=30)
    try:
        send_assignment_emails_job()
    except Exception as e:
        log.error("notify after series add failed: %s", e)
    # korrekt auf die Seite mit deinem echten Token umleiten
    return RedirectResponse(url=f"/admin/{token}/series", status_code=303)



# POST /series/toggle
@router.post("/series/toggle")
async def admin_series_toggle(token: str, series_id: int = Form(...), db=Depends(get_db)):
    if not _is_admin_token(token, db): raise HTTPException(status_code=403)
    s = db.get(TaskSeries, series_id)
    if not s: raise HTTPException(status_code=404)
    s.active = not s.active
    db.commit()
    return RedirectResponse(url=f"/admin/{token}/series", status_code=303)



# POST /series/delete
@router.post("/series/delete")
async def admin_series_delete(token: str, series_id: int = Form(...), delete_future: int = Form(0), db=Depends(get_db)):
    if not _is_admin_token(token, db): raise HTTPException(status_code=403)
    s = db.get(TaskSeries, series_id)
    if not s: raise HTTPException(status_code=404)
    # optionally delete future occurrences
    if delete_future:
        today_s = today_iso()
        q = db.query(Task).filter(Task.series_id==series_id, Task.date >= today_s)
        for t in q.all():
            db.delete(t)
    db.delete(s)
    db.commit()
    return RedirectResponse(url=f"/admin/{token}/series", status_code=303)



# POST /series/update
@router.post("/series/update")
async def admin_series_update(
    token: str,
    series_id: int = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    apartment_id_raw: str = Form(""),
    staff_id_raw: str = Form(""),
    planned_minutes: int = Form(60),
    start_date: str = Form(...),
    start_time: str = Form(""),
    frequency: str = Form(...),
    interval: int = Form(1),
    byweekday: str = Form(""),
    bymonthday: str = Form(""),
    end_date: str = Form(""),
    count: int | None = Form(None),
    db=Depends(get_db)
):
    if not _is_admin_token(token, db):
        raise HTTPException(status_code=403)
    s = db.get(TaskSeries, series_id)
    if not s:
        raise HTTPException(status_code=404)
    apt_id = None
    if apartment_id_raw.strip():
        try:
            aid = int(apartment_id_raw)
            if aid > 0:
                apt_id = aid
        except Exception:
            pass
    staff_id = None
    if staff_id_raw.strip():
        try:
            sid = int(staff_id_raw)
            if sid > 0:
                staff_id = sid
        except Exception:
            pass
    s.title = title.strip()
    s.description = description.strip()
    s.apartment_id = apt_id
    s.staff_id = staff_id
    s.planned_minutes = planned_minutes
    s.start_date = start_date[:10]
    s.start_time = start_time[:5] if start_time else ""
    s.frequency = frequency
    s.interval = max(1, int(interval or 1))
    s.byweekday = byweekday.strip()
    s.bymonthday = bymonthday.strip()
    s.end_date = (end_date[:10] if end_date else None)
    s.count = (int(count) if (str(count).strip().isdigit()) else None)
    db.commit()
    return RedirectResponse(url=f"/admin/{token}/series", status_code=303)



# GET /series/expand
@router.get("/series/expand")
async def admin_series_expand(token: str, days: int = 30):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    created = expand_series_job(days_ahead=days)
    try:
        if created:
            send_assignment_emails_job()
    except Exception as e:
        log.error("notify after series expand failed: %s", e)
    return PlainTextResponse(f"Created {created} tasks for next {days} days.")



# GET /staff
@router.get("/staff")
async def admin_staff(request: Request, token: str, db=Depends(get_db)):
    if not _is_admin_token(token, db):
        raise HTTPException(status_code=403)
    lang = detect_language(request)
    trans = get_translations(lang)
    staff = db.query(Staff).order_by(Staff.name).all()
    
    # Berechne Stunden (geleistet & geplant) für jeden Mitarbeiter (vorletzter, letzter, aktueller Monat)
    today = dt.date.today()
    current_month = today.strftime("%Y-%m")
    
    # Berechne vorletzten und letzten Monat
    if today.month >= 3:
        last_month = (today.year, today.month - 1)
        prev_last_month = (today.year, today.month - 2)
    elif today.month == 2:
        last_month = (today.year, 1)
        prev_last_month = (today.year - 1, 12)
    else:  # today.month == 1
        last_month = (today.year - 1, 12)
        prev_last_month = (today.year - 1, 11)
    
    last_month_str = f"{last_month[0]}-{last_month[1]:02d}"
    prev_last_month_str = f"{prev_last_month[0]}-{prev_last_month[1]:02d}"

    # Monatsgrenzen (für geplante Zeiten)
    def month_range(year: int, month: int):
        start = dt.date(year, month, 1)
        if month == 12:
            end = dt.date(year + 1, 1, 1) - dt.timedelta(days=1)
        else:
            end = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
        return start.isoformat(), end.isoformat()

    prev_start, prev_end = month_range(prev_last_month[0], prev_last_month[1])
    last_start, last_end = month_range(last_month[0], last_month[1])
    curr_start, curr_end = month_range(today.year, today.month)
    
    staff_hours = {}
    for s in staff:
        # Hole alle TimeLog-Einträge für diesen Mitarbeiter mit actual_minutes
        logs = db.query(TimeLog).filter(
            TimeLog.staff_id == s.id,
            TimeLog.actual_minutes != None
        ).all()
        
        hours_data = {
            'prev_last_month': 0.0,
            'last_month': 0.0,
            'current_month': 0.0,
            'prev_last_planned': 0.0,
            'last_planned': 0.0,
            'current_planned': 0.0,
            'prev_last_total': 0.0,
            'last_total': 0.0,
            'current_total': 0.0,
        }
        
        for tl in logs:
            if not tl.started_at:
                continue
            
            # Extrahiere Monat aus started_at (Format: "yyyy-mm-dd HH:MM:SS")
            month_str = tl.started_at[:7]  # "yyyy-mm"
            minutes = int(tl.actual_minutes or 0)
            hours = round(minutes / 60.0, 2)
            
            if month_str == prev_last_month_str:
                hours_data['prev_last_month'] += hours
            elif month_str == last_month_str:
                hours_data['last_month'] += hours
            elif month_str == current_month:
                hours_data['current_month'] += hours
        
        # Geplante Zeiten aus Tasks (planned_minutes)
        def planned_hours_for_range(start_iso: str, end_iso: str) -> float:
            tasks = db.query(Task).filter(
                Task.assigned_staff_id == s.id,
                Task.date >= start_iso,
                Task.date <= end_iso,
            ).all()
            minutes = sum(int(t.planned_minutes or 0) for t in tasks)
            return round(minutes / 60.0, 2)

        hours_data['prev_last_planned'] = planned_hours_for_range(prev_start, prev_end)
        hours_data['last_planned'] = planned_hours_for_range(last_start, last_end)
        hours_data['current_planned'] = planned_hours_for_range(curr_start, curr_end)

        # Gesamtsummen (geleistet + geplant)
        hours_data['prev_last_total'] = round(hours_data['prev_last_month'] + hours_data['prev_last_planned'], 2)
        hours_data['last_total'] = round(hours_data['last_month'] + hours_data['last_planned'], 2)
        hours_data['current_total'] = round(hours_data['current_month'] + hours_data['current_planned'], 2)

        # Runde Ist-Zeiten auf 2 Dezimalstellen
        hours_data['prev_last_month'] = round(hours_data['prev_last_month'], 2)
        hours_data['last_month'] = round(hours_data['last_month'], 2)
        hours_data['current_month'] = round(hours_data['current_month'], 2)
        
        staff_hours[s.id] = hours_data
    
    base_url = BASE_URL.rstrip("/")
    if not base_url:
        base_url = f"{request.url.scheme}://{request.url.hostname}" + (f":{request.url.port}" if request.url.port else "")
    return templates.TemplateResponse("admin_staff.html", {"request": request, "token": token, "staff": staff, "staff_hours": staff_hours, "current_month": current_month, "last_month": last_month_str, "prev_last_month": prev_last_month_str, "base_url": base_url, "lang": lang, "trans": trans})



# POST /staff/add
@router.post("/staff/add")
async def admin_staff_add(token: str, name: str = Form(...), email: str = Form(...), phone: str = Form(""), hourly_rate: float = Form(0.0), max_hours_per_month: int = Form(160), language: str = Form("de"), is_admin: int = Form(0), db=Depends(get_db)):
    if not _is_admin_token(token, db): raise HTTPException(status_code=403)
    email = (email or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="E-Mail ist erforderlich")
    if language not in ["de","en","fr","it","es","ro","ru","bg"]:
        language = "de"
    phone = (phone or "").strip()
    s = Staff(name=name, email=email, phone=phone, hourly_rate=hourly_rate, max_hours_per_month=max_hours_per_month, magic_token=new_token(16), active=True, language=language, is_admin=bool(is_admin))
    db.add(s); db.commit()
    return RedirectResponse(url=f"/admin/{token}/staff", status_code=303)



# POST /staff/toggle
@router.post("/staff/toggle")
async def admin_staff_toggle(token: str, staff_id: int = Form(...), db=Depends(get_db)):
    if not _is_admin_token(token, db): raise HTTPException(status_code=403)
    s = db.get(Staff, staff_id); s.active = not s.active; db.commit()
    return RedirectResponse(url=f"/admin/{token}/staff", status_code=303)



# POST /staff/update
@router.post("/staff/update")
async def admin_staff_update(
    token: str,
    staff_id: int = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(""),
    hourly_rate: float = Form(0.0),
    max_hours_per_month: int = Form(160),
    language: str = Form("de"),
    is_admin: int = Form(0),
    db=Depends(get_db)
):
    if not _is_admin_token(token, db):
        raise HTTPException(status_code=403)
    s = db.get(Staff, staff_id)
    if not s:
        raise HTTPException(status_code=404, detail="Staff nicht gefunden")
    email = (email or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Ungültige E-Mail")
    if language not in ["de","en","fr","it","es","ro","ru","bg"]:
        language = "de"
    phone = (phone or "").strip()
    s.name = name
    s.email = email
    s.phone = phone
    s.hourly_rate = float(hourly_rate or 0)
    s.max_hours_per_month = int(max_hours_per_month or 0)
    s.language = language
    s.is_admin = bool(is_admin)
    db.commit()
    return RedirectResponse(url=f"/admin/{token}/staff", status_code=303)



# POST /staff/delete
@router.post("/staff/delete")
async def admin_staff_delete(token: str, staff_id: int = Form(...), db=Depends(get_db)):
    if not _is_admin_token(token, db):
        raise HTTPException(status_code=403)
    s = db.get(Staff, staff_id)
    if not s:
        raise HTTPException(status_code=404, detail="Staff nicht gefunden")
    # Entkopple Aufgaben
    for t in db.query(Task).filter(Task.assigned_staff_id==s.id).all():
        t.assigned_staff_id = None
        t.assignment_status = None
    # Lösche TimeLogs des Mitarbeiters
    for tl in db.query(TimeLog).filter(TimeLog.staff_id==s.id).all():
        db.delete(tl)
    db.delete(s)
    db.commit()
    return RedirectResponse(url=f"/admin/{token}/staff", status_code=303)



# POST /task/assign
@router.post("/task/assign")
async def admin_task_assign(request: Request, token: str, task_id: int = Form(...), staff_id_raw: str = Form(""), db=Depends(get_db)):
    if not _is_admin_token(token, db): raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task nicht gefunden")
    prev_staff_id = t.assigned_staff_id
    staff_id: Optional[int] = int(staff_id_raw) if staff_id_raw.strip() else None
    t.assigned_staff_id = staff_id
    # Setze assignment_status auf "pending" wenn ein MA zugewiesen wird, sonst None
    if staff_id:
        t.assignment_status = "pending"
        # Markiere für Benachrichtigung
        t.assign_notified_at = None
    else:
        t.assignment_status = None
    db.commit()
    # Sofortige Mail bei neuer/ändernder Zuweisung
    try:
        if staff_id and staff_id != prev_staff_id:
            send_assignment_emails_job()
    except Exception as e:
        log.error("Immediate notify failed for task %s: %s", t.id, e)
    # Behalte Filter-Parameter bei
    referer = request.headers.get("referer", "")
    if referer:
        try:
            from urllib.parse import urlparse, parse_qs, urlencode
            parsed = urlparse(referer)
            params = parse_qs(parsed.query)
            query_parts = []
            if params.get("show_done"):
                query_parts.append(f"show_done={params['show_done'][0]}")
            if params.get("show_open"):
                query_parts.append(f"show_open={params['show_open'][0]}")
            if query_parts:
                return RedirectResponse(url=f"/admin/{token}?{'&'.join(query_parts)}", status_code=303)
        except Exception:
            pass
    return RedirectResponse(url=f"/admin/{token}", status_code=303)



# POST /task/create
@router.post("/task/create")
async def admin_task_create(
    token: str,
    date: str = Form(...),
    apartment_id: str = Form(""),
    planned_minutes: int = Form(90),
    description: str = Form(""),
    staff_id: str = Form(""),
    db=Depends(get_db),
):
    if not _is_admin_token(token, db):
        raise HTTPException(status_code=403)
    
    # Validierung
    if not date or not date.strip():
        raise HTTPException(status_code=400, detail="Datum ist erforderlich")
    
    # Apartment-ID optional - kann leer sein für manuelle Aufgaben
    apartment_id_val: Optional[int] = None
    apt_name = "Manuelle Aufgabe"
    if apartment_id and apartment_id.strip():
        try:
            apartment_id_val = int(apartment_id)
            if apartment_id_val > 0:
                apt = db.get(Apartment, apartment_id_val)
                if apt:
                    apt_name = apt.name
                else:
                    apartment_id_val = None  # Ungültige Apartment-ID ignorieren
            else:
                apartment_id_val = None  # 0 oder negativ = keine Apartment
        except (ValueError, TypeError):
            apartment_id_val = None
    
    # Staff-ID optional
    staff_id_val: Optional[int] = None
    if staff_id and staff_id.strip():
        try:
            staff_id_val = int(staff_id)
            staff = db.get(Staff, staff_id_val)
            if not staff:
                staff_id_val = None  # Ungültige Staff-ID ignorieren
        except ValueError:
            staff_id_val = None
    
    # Neue Aufgabe erstellen
    new_task = Task(
        date=date[:10],  # Nur Datum, ohne Zeit
        apartment_id=apartment_id_val,  # Kann None sein für manuelle Aufgaben
        planned_minutes=planned_minutes,
        notes=(description[:2000] if description else None),  # Beschreibung als Notiz speichern
        assigned_staff_id=staff_id_val,
        assignment_status="pending" if staff_id_val else None,
        status="open",
        auto_generated=False  # Manuell erstellt
    )
    db.add(new_task)
    db.commit()

    log.info("✅ Manuell erstellte Aufgabe: %s für %s am %s", new_task.id, apt_name, date)

    # Wenn ein MA ausgewählt wurde, direkt Benachrichtigung auslösen
    if staff_id_val:
        try:
            send_assignment_emails_job()
        except Exception as e:
            log.error("Fehler beim Senden der Zuweisungs-Benachrichtigung für manuelle Aufgabe %s: %s", new_task.id, e)

    return RedirectResponse(url=f"/admin/{token}", status_code=303)



# POST /task/delete
@router.post("/task/delete")
async def admin_task_delete(token: str, task_id: int = Form(...), db=Depends(get_db)):
    if not _is_admin_token(token, db):
        raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task nicht gefunden")
    if t.auto_generated:
        raise HTTPException(status_code=400, detail="Automatisch erzeugte Aufgaben können hier nicht gelöscht werden")
    for tl in db.query(TimeLog).filter(TimeLog.task_id==t.id).all():
        db.delete(tl)
    db.delete(t)
    db.commit()
    return RedirectResponse(url=f"/admin/{token}", status_code=303)



# POST /task/update_manual
@router.post("/task/update_manual")
async def admin_task_update_manual(token: str, task_id: int = Form(...), date: str = Form(...), apartment_id: str = Form(""), planned_minutes: int = Form(90), description: str = Form(""), staff_id: str = Form(""), db=Depends(get_db)):
    if not _is_admin_token(token, db):
        raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task nicht gefunden")
    if t.auto_generated:
        raise HTTPException(status_code=400, detail="Automatisch erzeugte Aufgaben können hier nicht bearbeitet werden")
    
    # Validierung
    if not date or not date.strip():
        raise HTTPException(status_code=400, detail="Datum ist erforderlich")
    
    # Apartment-ID optional
    apartment_id_val: Optional[int] = None
    if apartment_id and apartment_id.strip():
        try:
            apartment_id_val = int(apartment_id)
            if apartment_id_val > 0:
                apt = db.get(Apartment, apartment_id_val)
                if not apt:
                    apartment_id_val = None
            else:
                apartment_id_val = None
        except (ValueError, TypeError):
            apartment_id_val = None
    
    # Staff-ID optional
    staff_id_val: Optional[int] = None
    prev_staff_id = t.assigned_staff_id
    if staff_id and staff_id.strip():
        try:
            staff_id_val = int(staff_id)
            staff = db.get(Staff, staff_id_val)
            if not staff:
                staff_id_val = None
        except ValueError:
            staff_id_val = None
    
    # Task aktualisieren
    t.date = date[:10]
    t.apartment_id = apartment_id_val
    t.planned_minutes = planned_minutes
    t.notes = (description[:2000] if description else None)
    
    # Zuweisung aktualisieren
    t.assigned_staff_id = staff_id_val
    if staff_id_val:
        # Wenn ein MA zugewiesen wird, setze auf pending (außer wenn bereits accepted)
        if t.assignment_status != "accepted":
            t.assignment_status = "pending"
    else:
        # Wenn kein MA mehr zugewiesen, entferne Zuweisungsstatus
        t.assignment_status = None
    
    db.commit()
    
    # Wenn ein neuer MA zugewiesen wurde (oder geändert), Benachrichtigung senden
    if staff_id_val and staff_id_val != prev_staff_id:
        try:
            send_assignment_emails_job()
        except Exception as e:
            log.error("Fehler beim Senden der Zuweisungs-Benachrichtigung nach Update: %s", e)
    
    log.info("✅ Manuelle Aufgabe %s aktualisiert", t.id)
    return RedirectResponse(url=f"/admin/{token}", status_code=303)



# POST /task/status
@router.post("/task/status")
async def admin_task_status(token: str, task_id: int = Form(...), status: str = Form(...), db=Depends(get_db)):
    if not _is_admin_token(token, db):
        raise HTTPException(status_code=403)
    allowed = {"open", "paused", "done"}
    status = (status or "").strip().lower()
    if status not in allowed:
        raise HTTPException(status_code=400, detail="Ungültiger Status")
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task nicht gefunden")
    # TimeLogs behandeln: offene Logs schließen, wenn nicht 'running'
    tl = db.query(TimeLog).filter(TimeLog.task_id==t.id, TimeLog.ended_at==None).order_by(TimeLog.id.desc()).first()
    if tl:
        from datetime import datetime
        fmt = "%Y-%m-%d %H:%M:%S"
        tl.ended_at = now_iso()
        try:
            start = datetime.strptime(tl.started_at, fmt)
            end = datetime.strptime(tl.ended_at, fmt)
            elapsed = int((end-start).total_seconds()//60)
            tl.actual_minutes = int(tl.actual_minutes or 0) + max(0, elapsed)
        except Exception:
            pass
    t.status = status
    db.commit()
    return RedirectResponse(url=f"/admin/{token}", status_code=303)




# POST /task/extras
@router.post("/task/extras")
async def admin_task_extras(
    request: Request,
    token: str,
    task_id: int = Form(...),
    field: str = Form(...),
    value: str = Form("0"),
    redirect: str = Form(""),
    db=Depends(get_db),
):
    if not _is_admin_token(token, db):
        raise HTTPException(status_code=403)
    allowed_fields = {"kurtaxe_registriert", "kurtaxe_bestaetigt", "checkin_vorbereitet", "kurtaxe_bezahlt", "baby_beds"}
    field = (field or "").strip()
    if field not in allowed_fields:
        raise HTTPException(status_code=400, detail="Ungültiges Feld")
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task nicht gefunden")
    try:
        extras = json.loads(t.extras_json or "{}") or {}
    except Exception:
        extras = {}
    value_str = (value or "").strip().lower()
    if field == "baby_beds":
        try:
            beds = int(value_str)
        except ValueError:
            beds = 0
        beds = max(0, min(2, beds))
        extras[field] = beds
        response_value = beds
    else:
        flag = value_str in {"1", "true", "yes", "on"}
        extras[field] = flag
        response_value = flag
    t.extras_json = json.dumps(extras)
    db.commit()
    if (request.headers.get("x-requested-with") or "").lower() == "fetch":
        return JSONResponse({"ok": True, "task_id": t.id, "field": field, "value": response_value})
    target = redirect or request.headers.get("referer") or f"/admin/{token}"
    return RedirectResponse(url=target, status_code=303)



# GET /apartments
@router.get("/apartments")
async def admin_apartments(request: Request, token: str, db=Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403)
    lang = detect_language(request)
    trans = get_translations(lang)
    apts = db.query(Apartment).order_by(Apartment.name).all()
    return templates.TemplateResponse("admin_apartments.html", {"request": request, "token": token, "apartments": apts, "lang": lang, "trans": trans})



# POST /apartments/update
@router.post("/apartments/update")
async def admin_apartments_update(token: str, apartment_id: int = Form(...), planned_minutes: int = Form(...), db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    a = db.get(Apartment, apartment_id)
    a.planned_minutes = int(planned_minutes)
    db.commit()
    return RedirectResponse(url=f"/admin/{token}/apartments", status_code=303)



# POST /apartments/apply
@router.post("/apartments/apply")
async def admin_apartments_apply(token: str, apartment_id: int = Form(...), db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    a = db.get(Apartment, apartment_id)
    if not a:
        raise HTTPException(status_code=404, detail="Apartment nicht gefunden")
    
    # Get today's date
    today_iso = dt.date.today().isoformat()
    
    # Update all tasks for this apartment that are today or in the future
    tasks = db.query(Task).filter(
        Task.apartment_id == apartment_id,
        Task.date >= today_iso
    ).all()
    
    updated = 0
    for t in tasks:
        t.planned_minutes = a.planned_minutes
        # Benachrichtigung bei geänderter Dauer für zugewiesene (bündeln via Scheduler)
        if t.assigned_staff_id and t.assignment_status != "rejected":
            t.assign_notified_at = None
        updated += 1
    
    db.commit()
    log.info("Updated %d tasks for apartment %s to %d minutes", updated, a.name, a.planned_minutes)
    return RedirectResponse(url=f"/admin/{token}/apartments", status_code=303)



# GET /import
@router.get("/import")
async def admin_import(token: str, db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    await refresh_bookings_job()
    return PlainTextResponse("Import done.")



# GET /test_whatsapp
@router.get("/test_whatsapp")
async def admin_test_whatsapp(token: str, phone: str = Query(...), db=Depends(get_db)):
    """Test WhatsApp-Versand"""
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403)
    
    test_msg = "🧪 Test-Nachricht von Staff Planner"
    
    config_status = {
        "TWILIO_ACCOUNT_SID": "✅ gesetzt" if TWILIO_ACCOUNT_SID else "❌ nicht gesetzt",
        "TWILIO_AUTH_TOKEN": "✅ gesetzt" if TWILIO_AUTH_TOKEN else "❌ nicht gesetzt",
        "TWILIO_WHATSAPP_FROM": TWILIO_WHATSAPP_FROM if TWILIO_WHATSAPP_FROM else "❌ nicht gesetzt",
    }
    
    try:
        from twilio.rest import Client
        twilio_installed = "✅ installiert"
    except ImportError:
        twilio_installed = "❌ nicht installiert"
        return PlainTextResponse(f"❌ Twilio Library nicht installiert")
    
    # Versuche Nachricht zu senden und hole Details
    result = False
    message_details = {}
    normalized_phone = phone
    whatsapp_to = ""
    try:
        # Normalisiere Telefonnummer wie in _send_whatsapp
        normalized_phone = phone.strip().replace(" ", "").replace("-", "")
        if not normalized_phone.startswith("+"):
            if normalized_phone.startswith("0"):
                normalized_phone = "+49" + normalized_phone[1:]
            else:
                normalized_phone = "+49" + normalized_phone
        whatsapp_to = f"whatsapp:{normalized_phone}"
        
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        message_obj = client.messages.create(
            body=test_msg,
            from_=TWILIO_WHATSAPP_FROM,
            to=whatsapp_to
        )
        message_details = {
            "sid": message_obj.sid,
            "status": getattr(message_obj, 'status', 'unknown'),
            "error_code": getattr(message_obj, 'error_code', None),
            "error_message": getattr(message_obj, 'error_message', None),
            "price": getattr(message_obj, 'price', None),
            "price_unit": getattr(message_obj, 'price_unit', None),
        }
        result = message_details['status'] in ['queued', 'sent', 'delivered']
    except Exception as e:
        message_details = {"error": str(e)}
    
    response_text = (
        f"WhatsApp Test\n"
        f"=============\n\n"
        f"Telefonnummer (Eingabe): {phone}\n"
        f"Telefonnummer (normalisiert): {normalized_phone}\n"
        f"WhatsApp To: {whatsapp_to}\n\n"
        f"Ergebnis: {'✅ Erfolgreich' if result else '❌ Fehlgeschlagen'}\n\n"
        f"Message Details:\n"
        f"- SID: {message_details.get('sid', 'N/A')}\n"
        f"- Status: {message_details.get('status', 'N/A')}\n"
        f"- Error Code: {message_details.get('error_code', 'N/A')}\n"
        f"- Error Message: {message_details.get('error_message', 'N/A')}\n"
        f"- Price: {message_details.get('price', 'N/A')} {message_details.get('price_unit', '')}\n\n"
        f"Konfiguration:\n"
        f"- Twilio Library: {twilio_installed}\n"
        f"- Account SID: {config_status['TWILIO_ACCOUNT_SID']}\n"
        f"- Auth Token: {config_status['TWILIO_AUTH_TOKEN']}\n"
        f"- WhatsApp From: {config_status['TWILIO_WHATSAPP_FROM']}\n\n"
        f"Hinweis: Wenn Status 'queued' ist, wurde die Nachricht an Twilio gesendet.\n"
        f"Falls keine Nachricht ankommt, prüfe:\n"
        f"1. Ist die Nummer bei Twilio WhatsApp Sandbox verifiziert?\n"
        f"2. Ist TWILIO_WHATSAPP_FROM korrekt formatiert (whatsapp:+14155238886)?\n"
        f"3. Prüfe Twilio Console für Delivery-Status: https://console.twilio.com/\n"
    )
    
    return PlainTextResponse(response_text)



# GET /notify_assignments
@router.get("/notify_assignments")
async def admin_notify_assignments(token: str):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403)
    try:
        report = send_assignment_emails_job()
        if not report:
            return PlainTextResponse("Keine offenen Zuweisungen zum Versenden.")
        # Baue menschenlesbaren Report
        lines = ["Benachrichtigungen gesendet:", ""]
        for r in report:
            lines.append(f"- {r['staff_name']} <{r['email']}>: {r['count']} Aufgaben")
            for it in r['items']:
                guest = f" · {it['guest']}" if it.get('guest') else ""
                lines.append(f"  • {it['date']} · {it['apt']} · {it['desc']}{guest}")
            lines.append("")
        return PlainTextResponse("\n".join(lines).strip())
    except Exception as e:
        log.exception("Manual notify failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))



# GET /notify_whatsapp_existing
@router.get("/notify_whatsapp_existing")
async def admin_notify_whatsapp_existing(token: str):
    """Sende WhatsApp-Benachrichtigungen für bestehende Zuweisungen (auch wenn bereits per Email benachrichtigt)"""
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403)
    try:
        report = send_whatsapp_for_existing_assignments()
        if not report:
            return PlainTextResponse("Keine bestehenden Zuweisungen mit Telefonnummern gefunden.")
        # Baue menschenlesbaren Report
        lines = ["WhatsApp-Benachrichtigungen für bestehende Zuweisungen:", ""]
        for r in report:
            lines.append(f"- {r['staff_name']} ({r['phone']}): {r['count']} Aufgaben")
            for it in r['items']:
                guest = f" · {it['guest']}" if it.get('guest') else ""
                lines.append(f"  • {it['date']} · {it['apt']} · {it['desc']}{guest}")
            lines.append("")
        return PlainTextResponse("\n".join(lines).strip())
    except Exception as e:
        log.exception("WhatsApp notify existing failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))



# GET /cleanup_tasks
@router.get("/cleanup_tasks")
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



# GET /cleanup
@router.get("/cleanup")
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
    return PlainTextResponse(f"Cleanup done. Removed {removed_count} invalid tasks. Check logs for details.")



# GET /export
@router.get("/export")
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



# POST /push/test
@router.post("/push/test")
async def admin_push_test(token: str, staff_id: Optional[int] = Form(None), db=Depends(get_db)):
    if not _is_admin_token(token, db):
        raise HTTPException(status_code=403)
    q = db.query(PushSubscription)
    if staff_id:
        q = q.filter(PushSubscription.staff_id==staff_id)
    subs = q.all()
    sent = 0
    for sub in subs:
        ok = _send_webpush_to_subscription(sub, {"title": "Test", "body": "Web Push funktioniert.", "url": f"/admin/{token}"})
        if ok: sent += 1
    return JSONResponse({"ok": True, "sent": sent})

