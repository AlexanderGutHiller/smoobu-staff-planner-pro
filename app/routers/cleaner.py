"""Cleaner routes"""
import json
import datetime as dt
from typing import Optional, Dict
from fastapi import APIRouter, Request, Depends, Form, HTTPException, Query
from fastapi.responses import RedirectResponse, PlainTextResponse, HTMLResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..dependencies import get_db
from ..helpers import detect_language, get_translations
from ..shared import templates
from ..config import BASE_URL
from ..models import Staff, Apartment, Task, TimeLog, Booking
from ..utils import now_iso
from ..main import log

router = APIRouter(prefix="/cleaner/{token}", tags=["cleaner"])
router_short = APIRouter(prefix="/c/{token}", tags=["cleaner"])


def _build_cleaner_redirect_url(token: str, request: Request, task_id: Optional[int] = None) -> str:
    """Baut eine Redirect-URL mit allen Filter-Parametern aus dem Request"""
    from urllib.parse import urlparse, parse_qs, urlencode
    referer = request.headers.get("referer", "")
    base_url = f"/cleaner/{token}"
    
    # Anchor für Task-Scrolling
    anchor = f"#task-{task_id}" if task_id else ""
    
    if referer:
        try:
            parsed = urlparse(referer)
            params = parse_qs(parsed.query)
            # Alle relevanten Filter-Parameter sammeln
            filter_params = {}
            for key in ["show_done", "show_open"]:
                if key in params and params[key]:
                    filter_params[key] = params[key][0]
            if filter_params:
                query_string = urlencode(filter_params)
                return f"{base_url}?{query_string}{anchor}"
        except Exception:
            pass
    
    return f"{base_url}{anchor}"


# Cleaner Routes

# GET /cleaner/{token} -> 
@router.get("")
async def cleaner_home(request: Request, token: str, show_done: int = 0, show_open: int = 1, db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    q = db.query(Task).filter(Task.assigned_staff_id==s.id)
    # Abgelehnte Tasks ausblenden - zeige nur Tasks die nicht rejected sind
    from sqlalchemy import or_
    q = q.filter(or_(Task.assignment_status != "rejected", Task.assignment_status.is_(None)))
    # Filter nach Status: erledigte und/oder offene Aufgaben
    status_filters = []
    if show_done:
        status_filters.append(Task.status == "done")
    if show_open:
        status_filters.append(Task.status != "done")
    if status_filters:
        q = q.filter(or_(*status_filters))
    else:
        # Wenn beide Filter deaktiviert sind, zeige nichts
        q = q.filter(Task.id == -1)  # Unmögliche Bedingung
    tasks = q.order_by(Task.date, Task.id).all()
    apts = db.query(Apartment).all()
    apt_map = {a.id: a.name for a in apts}
    bookings = db.query(Booking).all()
    book_map = {b.id: (b.guest_name or "").strip() for b in bookings if b.guest_name}
    booking_details_map = {b.id: {'adults': b.adults or 0, 'children': b.children or 0, 'guest_name': (b.guest_name or "").strip()} for b in bookings}
    # Stunden: vorletzter, letzter, aktueller Monat
    today = dt.date.today()
    current_month_str = today.strftime("%Y-%m")
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

    logs = db.query(TimeLog).filter(TimeLog.staff_id==s.id, TimeLog.actual_minutes!=None).all()
    minutes_current = 0
    minutes_last = 0
    minutes_prev_last = 0
    for tl in logs:
        if not tl.started_at:
            continue
        m = tl.started_at[:7]
        mins = int(tl.actual_minutes or 0)
        if m == current_month_str:
            minutes_current += mins
        elif m == last_month_str:
            minutes_last += mins
        elif m == prev_last_month_str:
            minutes_prev_last += mins
    hours_current = round(minutes_current/60.0, 2)
    hours_last = round(minutes_last/60.0, 2)
    hours_prev_last = round(minutes_prev_last/60.0, 2)
    used_hours = hours_current
    run_map: Dict[int, str] = {}
    for t in tasks:
        tl = db.query(TimeLog).filter(TimeLog.task_id==t.id, TimeLog.staff_id==s.id, TimeLog.ended_at==None).order_by(TimeLog.id.desc()).first()
        if tl:
            run_map[t.id] = tl.started_at
    has_running = any(t.status == 'running' for t in tasks)
    warn_limit = used_hours > float(s.max_hours_per_month or 0)
    # Timelog-Daten für jedes Task (für pausierte Aufgaben)
    timelog_map = {}
    for t in tasks:
        tl = db.query(TimeLog).filter(TimeLog.task_id==t.id, TimeLog.staff_id==s.id).order_by(TimeLog.id.desc()).first()
        if tl:
            timelog_map[t.id] = {
                'actual_minutes': tl.actual_minutes,
                'started_at': tl.started_at,
                'ended_at': tl.ended_at
            }
    extras_map: Dict[int, Dict[str, object]] = {}
    for t in tasks:
        try:
            extras_map[t.id] = json.loads(t.extras_json or "{}") or {}
        except Exception:
            extras_map[t.id] = {}
    lang = detect_language(request)
    trans = get_translations(lang)
    return templates.TemplateResponse("cleaner.html", {"request": request, "tasks": tasks, "used_hours": used_hours, "hours_prev_last": hours_prev_last, "hours_last": hours_last, "hours_current": hours_current, "apt_map": apt_map, "book_map": book_map, "booking_details_map": booking_details_map, "staff": s, "show_done": show_done, "show_open": show_open, "run_map": run_map, "timelog_map": timelog_map, "extras_map": extras_map, "warn_limit": warn_limit, "lang": lang, "trans": trans, "has_running": has_running})



# POST /cleaner/{token}/start -> /start
@router.post("/start")
async def cleaner_start(request: Request, token: str, task_id: int = Form(...), show_done: Optional[int] = Form(None), show_open: Optional[int] = Form(None), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t: raise HTTPException(status_code=404, detail="Task nicht gefunden")
    
    # Beende alle offenen TimeLogs dieses Staff (außer für den aktuellen Task, falls er pausiert ist)
    open_tls = db.query(TimeLog).filter(TimeLog.staff_id==s.id, TimeLog.ended_at==None, TimeLog.task_id!=task_id).all()
    for open_tl in open_tls:
        from datetime import datetime
        open_tl.ended_at = now_iso()
        fmt = "%Y-%m-%d %H:%M:%S"
        try:
            start = datetime.strptime(open_tl.started_at, fmt)
            end = datetime.strptime(open_tl.ended_at, fmt)
            elapsed = int((end-start).total_seconds()//60)
            if open_tl.actual_minutes:
                open_tl.actual_minutes += elapsed
            else:
                open_tl.actual_minutes = elapsed
        except Exception:
            pass
        # Setze den Status der anderen Tasks auf 'open'
        other_task = db.get(Task, open_tl.task_id)
        if other_task and other_task.status == 'running':
            other_task.status = 'open'
    
    # Prüfe ob bereits ein TimeLog für diesen Task existiert (pausierte Aufgabe)
    existing_tl = db.query(TimeLog).filter(TimeLog.task_id==task_id, TimeLog.staff_id==s.id, TimeLog.ended_at==None).order_by(TimeLog.id.desc()).first()
    if existing_tl:
        # Setze started_at auf jetzt, damit die Zeit weiterläuft
        existing_tl.started_at = now_iso()
    else:
        # Erstelle neues TimeLog für diesen Task
        existing_tl = TimeLog(task_id=task_id, staff_id=s.id, started_at=now_iso(), ended_at=None, actual_minutes=None)
        db.add(existing_tl)
    
    t.status = "running"
    db.commit()
    # Behalte Filter-Parameter bei
    return RedirectResponse(url=_build_cleaner_redirect_url(token, request), status_code=303)



# POST /cleaner/{token}/stop -> /stop
@router.post("/stop")
async def cleaner_stop(request: Request, token: str, task_id: int = Form(...), show_done: Optional[int] = Form(None), show_open: Optional[int] = Form(None), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t: raise HTTPException(status_code=404, detail="Task nicht gefunden")
    
    tl = db.query(TimeLog).filter(TimeLog.task_id==task_id, TimeLog.staff_id==s.id, TimeLog.ended_at==None).order_by(TimeLog.id.desc()).first()
    if tl:
        from datetime import datetime
        fmt = "%Y-%m-%d %H:%M:%S"
        # Speichere aktuelle Zeit, aber lasse ended_at auf None für spätere Fortsetzung
        # Berechne die bisherige Zeit
        try:
            start = datetime.strptime(tl.started_at, fmt)
            now = datetime.now()
            # Berechne bisherige Minuten und addiere zu eventuell bereits vorhandenen
            current_elapsed = int((now - start).total_seconds() // 60)
            if tl.actual_minutes:
                tl.actual_minutes += current_elapsed
            else:
                tl.actual_minutes = current_elapsed
            # Aktualisiere started_at auf jetzt, damit beim Weiterstarten die Zeit korrekt weiterläuft
            tl.started_at = now_iso()
            # Lassen ended_at auf None, damit wir wissen dass es pausiert ist
        except Exception as e:
            log.error("Error in cleaner_stop: %s", e)
            pass
    
    t.status = "paused"  # Status auf "paused" setzen statt "open"
    db.commit()
    # Behalte Filter-Parameter bei
    return RedirectResponse(url=_build_cleaner_redirect_url(token, request), status_code=303)



# POST /cleaner/{token}/done -> /done
@router.post("/done")
async def cleaner_done(request: Request, token: str, task_id: int = Form(...), show_done: Optional[int] = Form(None), show_open: Optional[int] = Form(None), db=Depends(get_db)):
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
            finished = int((end-start).total_seconds()//60)
            if tl.actual_minutes:
                tl.actual_minutes += finished
            else:
                tl.actual_minutes = finished
        except Exception:
            pass
    
    t.status = "done"
    db.commit()
    # Behalte Filter-Parameter bei
    return RedirectResponse(url=_build_cleaner_redirect_url(token, request), status_code=303)



# POST /cleaner/{token}/accept -> /accept
@router.post("/accept")
async def cleaner_accept(request: Request, token: str, task_id: int = Form(...), show_done: Optional[int] = Form(None), show_open: Optional[int] = Form(None), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t or t.assigned_staff_id != s.id:
        raise HTTPException(status_code=404, detail="Task nicht gefunden oder nicht zugewiesen")
    t.assignment_status = "accepted"
    db.commit()
    # Behalte Filter-Parameter bei und scrolle zur Task
    return RedirectResponse(url=_build_cleaner_redirect_url(token, request, task_id), status_code=303)



# POST /cleaner/{token}/reject -> /reject
@router.post("/reject")
async def cleaner_reject(request: Request, token: str, task_id: int = Form(...), show_done: Optional[int] = Form(None), show_open: Optional[int] = Form(None), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t or t.assigned_staff_id != s.id:
        raise HTTPException(status_code=404, detail="Task nicht gefunden oder nicht zugewiesen")
    t.assignment_status = "rejected"
    db.commit()
    # Behalte Filter-Parameter bei und scrolle zur Task
    return RedirectResponse(url=_build_cleaner_redirect_url(token, request, task_id), status_code=303)



# POST /cleaner/{token}/reopen -> /reopen
@router.post("/reopen")
async def cleaner_reopen(request: Request, token: str, task_id: int = Form(...), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    tl = db.query(TimeLog).filter(TimeLog.task_id==task_id, TimeLog.staff_id==s.id).order_by(TimeLog.id.desc()).first()
    if tl:
        db.delete(tl)
    t.status = "open"
    db.commit()
    # Behalte Filter-Parameter bei (Standard: show_done=1 wenn keine Parameter vorhanden)
    return RedirectResponse(url=_build_cleaner_redirect_url(token, request), status_code=303)



# POST /cleaner/{token}/note -> /note
@router.post("/note")
async def cleaner_note(token: str, task_id: int = Form(...), note: str = Form(""), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    t.notes = (note or "").strip()
    db.commit()
    return JSONResponse({"ok": True, "task_id": t.id, "note": t.notes})



# POST /cleaner/{token}/task/create -> /task/create
@router.post("/task/create")
async def cleaner_task_create(request: Request, token: str, date: str = Form(...), planned_minutes: int = Form(90), description: str = Form(""), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s:
        raise HTTPException(status_code=403)
    # Validierung
    if not date or not date.strip():
        raise HTTPException(status_code=400, detail="Datum ist erforderlich")
    try:
        _ = dt.datetime.strptime(date[:10], "%Y-%m-%d")
    except Exception:
        raise HTTPException(status_code=400, detail="Ungültiges Datum")
    pm = int(planned_minutes or 0)
    if pm <= 0:
        pm = 30
    # Manuelle Aufgabe, dem Cleaner selbst zugeordnet
    t = Task(
        date=date[:10],
        apartment_id=None,
        planned_minutes=pm,
        notes=(description[:2000] if description else None),
        assigned_staff_id=s.id,
        assignment_status="accepted",
        status="open",
        auto_generated=False
    )
    db.add(t)
    db.commit()
    return RedirectResponse(url=_build_cleaner_redirect_url(token, request), status_code=303)



# POST /cleaner/{token}/task/delete -> /task/delete
@router.post("/task/delete")
async def cleaner_task_delete(request: Request, token: str, task_id: int = Form(...), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s:
        raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t or t.assigned_staff_id != s.id:
        raise HTTPException(status_code=404, detail="Task nicht gefunden oder nicht zugewiesen")
    if t.auto_generated:
        raise HTTPException(status_code=400, detail="Automatisch erzeugte Aufgaben können hier nicht gelöscht werden")
    # Timelogs für diesen Task entfernen
    for tl in db.query(TimeLog).filter(TimeLog.task_id==t.id).all():
        db.delete(tl)
    db.delete(t)
    db.commit()
    return RedirectResponse(url=_build_cleaner_redirect_url(token, request), status_code=303)



# GET /c/{token}/accept -> /accept
@router_short.get("/accept")
async def cleaner_accept_get(request: Request, token: str, task_id: int, db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t or t.assigned_staff_id != s.id:
        raise HTTPException(status_code=404, detail="Task nicht gefunden oder nicht zugewiesen")
    t.assignment_status = "accepted"
    db.commit()
    # Weiterleitung mit Anchor zur Task-Karte und Filter-Parametern
    return RedirectResponse(url=_build_cleaner_redirect_url(token, request, task_id), status_code=303)



# GET /c/{token}/reject -> /reject
@router_short.get("/reject")
async def cleaner_reject_get(request: Request, token: str, task_id: int, db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t or t.assigned_staff_id != s.id:
        raise HTTPException(status_code=404, detail="Task nicht gefunden oder nicht zugewiesen")
    t.assignment_status = "rejected"
    db.commit()
    # Weiterleitung mit Anchor zur Task-Karte und Filter-Parametern
    return RedirectResponse(url=_build_cleaner_redirect_url(token, request, task_id), status_code=303)


