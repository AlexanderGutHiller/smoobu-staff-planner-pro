import os, json, datetime as dt, csv, io, logging
from typing import List, Optional, Dict
from fastapi import FastAPI, Request, Depends, Form, HTTPException, Query
from fastapi.responses import RedirectResponse, StreamingResponse, PlainTextResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import date as _date, datetime as _dt, timedelta as _td
from pywebpush import webpush, WebPushException

from .db import init_db, SessionLocal
from .models import Booking, Staff, Apartment, Task, TimeLog, TaskSeries, PushSubscription
from .services_smoobu import SmoobuClient
from .utils import new_token, today_iso, now_iso
from .sync import upsert_tasks_from_bookings
from .jobs import refresh_bookings_job, expand_series_job, send_assignment_emails_job, send_whatsapp_for_existing_assignments
from .helpers import detect_language, get_translations

# Import configuration from config.py
from .config import (
    ADMIN_TOKEN, TIMEZONE, REFRESH_INTERVAL_MINUTES, BASE_URL,
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM,
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, TWILIO_WHATSAPP_CONTENT_SID,
    APP_VERSION, APP_BUILD_DATE, VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_EMAIL
)
from .shared import templates

log = logging.getLogger("smoobu")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Smoobu Staff Planner Pro (v6.3)")

# Register routers
from .routers import main as main_router, admin as admin_router, cleaner as cleaner_router, webhooks as webhooks_router, push as push_router
app.include_router(main_router.router)
app.include_router(admin_router.router)
app.include_router(cleaner_router.router)
app.include_router(cleaner_router.router_short)
app.include_router(webhooks_router.router)
app.include_router(push_router.router)
app.include_router(push_router.router_admin)

if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Service Worker aus static bereitstellen (Fallback, falls kein static-Ordner)
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
    # Bündel-E-Mails für Zuweisungen alle 30 Minuten
    scheduler.add_job(send_assignment_emails_job, IntervalTrigger(minutes=30))
    # Expand recurring TaskSeries daily
    scheduler.add_job(expand_series_job, IntervalTrigger(hours=24))
    scheduler.start()

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

def _daterange(days=60):
    start = dt.date.today()
    end = start + dt.timedelta(days=days)
    return start.isoformat(), end.isoformat()

def _best_guest_name(it: dict) -> str:
    guest = it.get("guest") or {}
    # Häufige Felder
    candidates = [
        guest.get("fullName"),
        (f"{guest.get('firstName','')} {guest.get('lastName','')}".strip() or None),
        (f"{it.get('firstName','')} {it.get('lastName','')}".strip() or None),
        it.get("guestName"),
        it.get("mainGuestName"),
        it.get("contactName"),
        it.get("name"),
        (it.get("contact") or {}).get("name"),
    ]
    for c in candidates:
        if c and isinstance(c, str) and c.strip():
            return c.strip()
    return ""

def _guest_count_label(it: dict) -> str:
    try:
        adults = it.get("adults")
        children = it.get("children")
        # Alternativ-Felder absichern
        if adults is None:
            adults = it.get("numAdults") or it.get("guests") or 0
        if children is None:
            children = it.get("numChildren") or 0
        adults = int(adults or 0)
        children = int(children or 0)
        total = adults + children
        if total <= 0 and (adults > 0 or children > 0):
            total = adults + children
        if total > 0:
            # Einfache deutsche Bezeichnung
            return f"{total} Gäste"
    except Exception:
        pass
    return ""

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
            if guest_name:
                log.debug("📝 Guest name for booking %d: '%s'", b_id, guest_name)
            else:
                # Breiteres Logging zur Diagnose, wenn kein Name geliefert wird
                try:
                    log.warning("⚠️ No guest name in booking %d. Available keys: %s", b_id, list(it.keys()))
                    if it.get("guest"):
                        log.warning("⚠️ guest keys: %s", list((it.get("guest") or {}).keys()))
                    if it.get("contact"):
                        log.warning("⚠️ contact keys: %s", list((it.get("contact") or {}).keys()))
                    log.warning("⚠️ adults=%s children=%s guests=%s", it.get("adults"), it.get("children"), it.get("guests"))
                except Exception:
                    pass
                # Fallback: Gästeanzahl
                guest_name = _guest_count_label(it) or ""
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
                # Sofort-Benachrichtigung an zugewiesene Cleaner über Storno + zugehörige Tasks löschen
                try:
                    # Sammle betroffene Tasks
                    tasks = db.query(Task).filter(Task.booking_id==b_id).all()
                    by_staff: Dict[int, list] = {}
                    for t in tasks:
                        if t.assigned_staff_id and t.assignment_status != "rejected":
                            by_staff.setdefault(t.assigned_staff_id, []).append(t)
                    for sid, tlist in by_staff.items():
                        staff = db.get(Staff, sid)
                        if not staff or not (staff.email or "").strip():
                            continue
                        lang = staff.language or "de"
                        trans = get_translations(lang)
                        # E-Mail-Inhalte pro Staff
                        items = []
                        for t in tlist:
                            token = staff.magic_token
                            items.append({
                                'date': t.date,
                                'apt': apt_name or "",
                                'desc': (t.notes or "").strip() or trans.get('tätigkeit','Tätigkeit'),
                                'link': f"{BASE_URL.rstrip('/')}/cleaner/{token}",
                            })
                        subject = f"{trans.get('cleanup','Bereinigen')}: {trans.get('zuweisung','Zuweisung')} storniert"
                        # Text
                        lines = [f"{trans.get('zuweisung','Zuweisung')} storniert:"]
                        for it in items:
                            lines.append(f"- {it['date']} · {it['apt']} · {it['desc']}")
                        lines.append("")
                        lines.append(items[0]['link'])
                        body_text = "\n".join(lines)
                        # HTML
                        cards = []
                        for it in items:
                            cards.append(f"""
                            <div style='border:1px solid #f1b0b7;border-radius:8px;padding:12px;margin:10px 0;background:#fff5f5;'>
                              <div style='display:flex;justify-content:space-between;align-items:center;'>
                                <div style='font-weight:700;font-size:16px'>{it['date']} · {it['apt']}</div>
                                <span style='background:#dc3545;color:#fff;border-radius:12px;padding:4px 8px;font-size:12px;'>Storniert</span>
                              </div>
                              <div style='margin-top:6px;font-size:14px;'>{it['desc']}</div>
                            </div>
                            """)
                        body_html = f"""
                        <div style='font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#f8f9fa;padding:16px;'>
                          <div style='max-width:680px;margin:0 auto;'>
                            <h2 style='margin:0 0 12px 0;font-size:20px;'>Storno: Aufgaben entfallen</h2>
                            {''.join(cards)}
                            <div style='margin-top:12px;'>
                              <a href='{items[0]['link']}' style='text-decoration:none;background:#0d6efd;color:#fff;padding:8px 10px;border-radius:6px;font-weight:600;'>Zur Übersicht</a>
                            </div>
                          </div>
                        </div>
                        """
                        _send_email(staff.email, subject, body_text, body_html)
                except Exception as e:
                    log.error("Error sending cancellation notifications for booking %d: %s", b_id, e)
                # Delete existing booking if it exists
                b_existing = db.get(Booking, b_id)
                if b_existing:
                    db.delete(b_existing)
                    log.info("🗑️ Deleted existing booking %d from database", b_id)
                # Lösche zugehörige Tasks direkt
                for t in db.query(Task).filter(Task.booking_id==b_id).all():
                    db.delete(t)
                db.commit()
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
            b.guest_name = (guest_name or "").strip()
            if b.guest_name:
                log.debug("✅ Saving guest name '%s' for booking %d", b.guest_name, b_id)
            else:
                log.warning("⚠️ No guest name found for booking %d (apt: %s)", b_id, apt_name)
            
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

# Helper functions for date parsing and series expansion
def _parse_date(s: str) -> _date | None:
    try:
        return _dt.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def _add_months(d: _date, months: int) -> _date:
    # simple month addition handling year wrap and end-of-month
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    # clamp day to last day of target month
    import calendar
    last_day = calendar.monthrange(y, m)[1]
    day = min(d.day, last_day)
    return _date(y, m, day)

def _daterange_iter(start: _date, end: _date):
    cur = start
    while cur <= end:
        yield cur
        cur = cur + _td(days=1)

def _expand_series_occurrences(series: TaskSeries, start_from: _date, until: _date) -> list[_date]:
    """Return list of dates to generate between start_from and until inclusive."""
    out: list[_date] = []
    if not series.active:
        return out
    s0 = _parse_date(series.start_date)
    if not s0:
        return out
    end_limit = _parse_date(series.end_date) if series.end_date else None
    hard_until = min(until, end_limit) if end_limit else until
    if hard_until < start_from:
        return out
    freq = (series.frequency or "").lower()
    interval = max(1, int(series.interval or 1))
    if freq == "weekly":
        # determine weekdays
        wd_map = {"mo":0,"tu":1,"we":2,"th":3,"fr":4,"sa":5,"su":6}
        if series.byweekday:
            wds = [wd_map.get(p.strip().lower()[:2]) for p in series.byweekday.split(",")]
            wds = [w for w in wds if w is not None]
            if not wds:
                wds = [s0.weekday()]
        else:
            wds = [s0.weekday()]
        # find the first week start aligned to interval
        # compute week index since start
        start_week_monday = s0 - _td(days=s0.weekday())
        for d in _daterange_iter(max(start_from, s0), hard_until):
            # check interval weeks from start
            windex = ((d - start_week_monday).days // 7)
            if windex % interval == 0 and d.weekday() in wds and d >= s0:
                out.append(d)
                if series.count and len(out) >= series.count:
                    break
    elif freq == "monthly":
        # bymonthday list or default to start day
        if series.bymonthday:
            mdays = []
            for p in series.bymonthday.split(","):
                try:
                    md = int(p.strip())
                    if 1 <= md <= 31:
                        mdays.append(md)
                except Exception:
                    pass
            if not mdays:
                mdays = [s0.day]
        else:
            mdays = [s0.day]
        # iterate months from s0 to hard_until
        cur = s0
        # set cur to first month that reaches start_from
        while cur < start_from:
            cur = _add_months(cur, interval)
        gen = 0
        while cur <= hard_until:
            import calendar
            last_day = calendar.monthrange(cur.year, cur.month)[1]
            for md in mdays:
                day = min(md, last_day)
                d = _date(cur.year, cur.month, day)
                if d < s0 or d < start_from or d > hard_until:
                    continue
                out.append(d)
                gen += 1
                if series.count and gen >= series.count:
                    return out
            cur = _add_months(cur, interval)
    elif freq == "yearly":
        cur = s0
        while cur < start_from:
            cur = _date(cur.year + interval, cur.month, cur.day)
        gen = 0
        while cur <= hard_until:
            if cur >= s0 and cur >= start_from:
                out.append(cur)
                gen += 1
                if series.count and gen >= series.count:
                    return out
            cur = _date(cur.year + interval, cur.month, cur.day)
    else:
        # unsupported; fallback: single occurrence at start_date if in window
        if s0 >= start_from and s0 <= hard_until:
            out.append(s0)
    return out

def expand_series_job(days_ahead: int = 30):
    """Generate tasks from active TaskSeries for the next days_ahead."""
    with SessionLocal() as db:
        horizon = _date.today() + _td(days=days_ahead)
        series_list = db.query(TaskSeries).filter(TaskSeries.active==True).all()
        created = 0
        new_tasks: list[Task] = []
        for ser in series_list:
            # find last generated date for this series
            last = db.query(Task).filter(Task.series_id==ser.id).order_by(Task.date.desc()).first()
            start_from = _parse_date(last.date) + _td(days=1) if last else _parse_date(ser.start_date) or _date.today()
            occ = _expand_series_occurrences(ser, start_from, horizon)
            for d in occ:
                # skip if task exists for same series+date
                exists = db.query(Task).filter(Task.series_id==ser.id, Task.date==(d.isoformat())).first()
                if exists:
                    continue
                t = Task(
                    date=d.isoformat(),
                    apartment_id=ser.apartment_id,
                    planned_minutes=ser.planned_minutes or 60,
                    notes=(ser.description or None),
                    assigned_staff_id=ser.staff_id,
                    assignment_status="pending" if ser.staff_id else None,
                    status="open",
                    auto_generated=False,
                    series_id=ser.id,
                    is_recurring=True
                )
                db.add(t)
                created += 1
                new_tasks.append(t)
        db.commit()
        # Sofort benachrichtigen, wenn neue Zuweisungen entstanden sind
        if created > 0:
            try:
                send_assignment_emails_job()
            except Exception as e:
                log.error("send_assignment_emails_job after series expansion failed: %s", e)
        log.info("🗓️ Series expansion created %d tasks up to %s", created, horizon.isoformat())
        return created

def minutes_to_hhmm(minutes: Optional[int]) -> str:
    """Konvertiere Minuten in hh:mm Format"""
    if minutes is None:
        return "--:--"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"

# Register template filters
templates.env.filters["date_de"] = date_de
templates.env.filters["date_wd_de"] = date_wd_de
templates.env.filters["minutes_to_hhmm"] = minutes_to_hhmm

def _send_email(to_email: str, subject: str, body_text: str, body_html: str | None = None):
    if not (SMTP_HOST and SMTP_FROM):
        log.warning("SMTP not configured, skipping email to %s", to_email)
        return
    import smtplib
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
            s.starttls()
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
        log.info("📧 Sent email to %s", to_email)
    except Exception as e:
        log.error("Email send failed to %s: %s", to_email, e)

def _send_whatsapp(to_phone: str, message: str | dict, use_template: bool = False):
    """Sende WhatsApp-Nachricht über Twilio
    
    Args:
        to_phone: Telefonnummer
        message: Nachrichtentext
        use_template: Wenn True, verwende Content SID (Opt-In-Vorlage), sonst freie Nachricht
    """
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM):
        log.warning("Twilio not configured, skipping WhatsApp to %s", to_phone)
        return False
    
    if not to_phone or not to_phone.strip():
        log.warning("No phone number provided for WhatsApp")
        return False
    
    try:
        from twilio.rest import Client
        
        # Normalisiere Telefonnummer (entferne Leerzeichen, füge + hinzu falls nötig)
        phone = to_phone.strip().replace(" ", "").replace("-", "")
        if not phone.startswith("+"):
            # Wenn keine Ländervorwahl, füge +49 für Deutschland hinzu (oder konfigurierbar)
            if phone.startswith("0"):
                phone = "+49" + phone[1:]  # 0171... -> +49171...
            else:
                phone = "+49" + phone  # 171... -> +49171...
        whatsapp_to = f"whatsapp:{phone}"
        
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        log.info("📱 Sending WhatsApp: from=%s, to=%s, message_length=%d, use_template=%s", 
                 TWILIO_WHATSAPP_FROM, whatsapp_to, len(message), use_template)
        
        # Status-Callback-URL für Delivery-Updates
        status_callback_url = None
        if BASE_URL:
            status_callback_url = f"{BASE_URL.rstrip('/')}/webhook/twilio/status"
        
        # Verwende WhatsApp-Vorlage (Content SID) wenn gewünscht und konfiguriert
        if use_template and TWILIO_WHATSAPP_CONTENT_SID:
            # message sollte hier ein dict mit Template-Variablen sein, nicht ein String
            if isinstance(message, dict):
                content_vars = message
            else:
                # Fallback: wenn message ein String ist, verwende Variable 1 (für Opt-In)
                content_vars = {"1": message}
            
            # Stelle sicher, dass alle Werte Strings sind (Twilio erwartet Strings)
            content_vars_str = {str(k): str(v) if v is not None else "" for k, v in content_vars.items()}
            
            # Debug: Logge die Variablen
            log.info("📱 Template variables: %s", json.dumps(content_vars_str))
            
            message_obj = client.messages.create(
                content_sid=TWILIO_WHATSAPP_CONTENT_SID,
                content_variables=json.dumps(content_vars_str),
                from_=TWILIO_WHATSAPP_FROM,
                to=whatsapp_to,
                status_callback=status_callback_url
            )
            log.info("📱 Using WhatsApp template (Content SID: %s, vars: %s)", TWILIO_WHATSAPP_CONTENT_SID, list(content_vars_str.keys()))
        else:
            # Freie Nachricht (nur innerhalb 24h-Fenster möglich)
            message_obj = client.messages.create(
                body=message,
                from_=TWILIO_WHATSAPP_FROM,
                to=whatsapp_to,
                status_callback=status_callback_url
            )
        status = getattr(message_obj, 'status', 'unknown')
        error_code = getattr(message_obj, 'error_code', None)
        error_message = getattr(message_obj, 'error_message', None)
        
        log.info("📱 WhatsApp API Response: SID=%s, Status=%s, ErrorCode=%s, ErrorMessage=%s", 
                message_obj.sid, status, error_code, error_message)
        
        if status in ['queued', 'sent', 'delivered']:
            log.info("✅ WhatsApp sent successfully to %s (Status: %s)", phone, status)
            return True
        elif status == 'failed':
            log.error("❌ WhatsApp failed to %s: %s (Code: %s)", phone, error_message, error_code)
            return False
        else:
            log.warning("⚠️ WhatsApp status unclear for %s: %s", phone, status)
            return True  # Return True anyway, as message was accepted by Twilio
    except ImportError:
        log.error("Twilio library not installed. Install with: pip install twilio")
        return False
    except Exception as e:
        log.error("WhatsApp send failed to %s: %s", to_phone, e, exc_info=True)
        return False

def _send_whatsapp_with_opt_in(to_phone: str, message: str | dict, staff_id: Optional[int] = None, db=None):
    """Sende WhatsApp-Nachricht mit Opt-In-Check
    
    WICHTIG: Templates können immer gesendet werden (auch ohne Opt-In-Bestätigung).
    Nur freie Nachrichten (Strings) benötigen Opt-In-Bestätigung.
    """
    # Prüfe Opt-In-Status
    opt_in_sent = False
    opt_in_confirmed = False
    if staff_id and db:
        staff = db.get(Staff, staff_id)
        if staff:
            opt_in_sent = getattr(staff, 'whatsapp_opt_in_sent', False)
            opt_in_confirmed = getattr(staff, 'whatsapp_opt_in_confirmed', False)
    
    # Wenn message ein dict ist, handelt es sich um ein Template
    is_template = isinstance(message, dict)
    
    # Templates können immer gesendet werden (auch ohne Opt-In-Bestätigung)
    if is_template:
        log.info("📱 Sending WhatsApp template to %s (templates don't require opt-in confirmation)", to_phone)
        return _send_whatsapp(to_phone, message, use_template=True)
    
    # Für freie Nachrichten (Strings) benötigen wir Opt-In-Bestätigung
    if not opt_in_confirmed:
        # Wenn Opt-In-Vorlage noch nicht gesendet wurde, sende sie jetzt
        if not opt_in_sent and TWILIO_WHATSAPP_CONTENT_SID:
            log.info("📱 Sending Opt-In message to %s (waiting for confirmation)", to_phone)
            opt_in_message = "Willkommen! Du erhältst ab jetzt Benachrichtigungen über neue Aufgaben."  # Kann angepasst werden
            opt_in_result = _send_whatsapp(to_phone, opt_in_message, use_template=True)
            if opt_in_result and staff_id and db:
                # Markiere Opt-In als gesendet (aber noch nicht bestätigt)
                staff = db.get(Staff, staff_id)
                if staff:
                    staff.whatsapp_opt_in_sent = True
                    db.commit()
                    log.info("✅ Opt-In message sent to staff %d (waiting for confirmation)", staff_id)
            # KEINE normale Nachricht senden, da Opt-In noch nicht bestätigt wurde
            return opt_in_result  # True wenn Opt-In-Vorlage erfolgreich gesendet wurde
        else:
            log.info("📱 Opt-In already sent to %s, waiting for confirmation before sending normal message", to_phone)
            # KEINE normale Nachricht senden, da Opt-In noch nicht bestätigt wurde
            return False
    
    # Opt-In wurde bestätigt - sende normale Nachricht
    log.info("📱 Opt-In confirmed for %s, sending normal message", to_phone)
    return _send_whatsapp(to_phone, message, use_template=False)

def build_assignment_whatsapp_message(lang: str, staff_name: str, items: list, base_url: str) -> str:
    """Erstellt eine WhatsApp-Nachricht (für nicht-Template-Versand)"""
    trans = get_translations(lang)
    msg = f"*{trans.get('zuweisung', 'Zuweisung')} · {staff_name}*\n\n"
    for i, it in enumerate(items, 1):
        msg += f"*{i}. {it['apt']}* - {it['date']}\n"
        if it['guest']:
            msg += f"👤 {it['guest']}\n"
        msg += f"📝 {it['desc']}\n"
        msg += f"✅ {it['accept']}\n"
        msg += f"❌ {it['reject']}\n\n"
    return msg

def build_assignment_whatsapp_template_vars(item: dict) -> dict:
    """Erstellt Template-Variablen für WhatsApp-Template 'staffplanning'
    
    Template erwartet:
    {{1}} = employee name
    {{2}} = room name
    {{3}} = room number
    {{4}} = date (YYYY-MM-DD)
    {{5}} = number of guests
    {{6}} = category / assignment type
    {{7}} = accept URL
    {{8}} = reject URL
    """
    import re
    # Extrahiere Raum-Nummer aus Raum-Name (z.B. "Romantik (9)" -> "9")
    room_name = item.get('apt', '') or 'Manuelle Aufgabe'
    room_number = ''
    if '(' in room_name and ')' in room_name:
        # Extrahiere Nummer aus Klammern
        match = re.search(r'\(([^)]+)\)', room_name)
        if match:
            room_number = match.group(1)
        # Entferne Klammern aus Raum-Name
        room_name = re.sub(r'\s*\([^)]+\)\s*', '', room_name).strip()
    else:
        room_number = ''
    
    # Anzahl Gäste (direkt aus item oder 0)
    guest_count = item.get('guest_count', 0)
    if guest_count is None:
        guest_count = 0
    guest_count_str = str(int(guest_count)) if guest_count else "0"
    
    # Stelle sicher, dass alle Werte Strings sind und nicht None/leer
    # Twilio erwartet, dass alle Variablen vorhanden sind, auch wenn sie leer sind
    staff_name = str(item.get('staff_name', '') or '').strip()
    date_str = str(item.get('date', '') or '').strip()
    desc_str = str(item.get('desc', 'Activity') or 'Activity').strip()
    accept_url = str(item.get('accept', '') or '').strip()
    reject_url = str(item.get('reject', '') or '').strip()
    
    # Validierung: Alle erforderlichen Felder müssen vorhanden sein
    if not staff_name:
        log.warning("⚠️ staff_name is empty in template vars for item: %s", item.get('date', 'unknown'))
    if not date_str:
        log.warning("⚠️ date is empty in template vars for item: %s", item.get('staff_name', 'unknown'))
    if not accept_url or not reject_url:
        log.warning("⚠️ URLs missing in template vars - accept: %s, reject: %s", accept_url, reject_url)
    
    return {
        "1": staff_name,  # employee name
        "2": str(room_name or ''),  # room name (ohne Nummer)
        "3": str(room_number or ''),  # room number
        "4": date_str,  # date (YYYY-MM-DD)
        "5": guest_count_str,  # number of guests
        "6": desc_str,  # category / assignment type
        "7": accept_url,  # accept URL
        "8": reject_url,  # reject URL
    }

def build_assignment_email(lang: str, staff_name: str, items: list, base_url: str) -> tuple[str, str, str]:
    trans = get_translations(lang)
    subject = f"{trans.get('zuweisung','Zuweisung')}: {len(items)} {trans.get('tasks','Tasks')}"
    # Text-Version
    tlines = [f"{trans.get('team','Team')}: {staff_name}", ""]
    for it in items:
        tlines.append(f"- {it['date']}: {it['desc']} ({it['apt']})")
        if it.get('guest'):
            tlines.append(f"  {it['guest']}")
        tlines.append(f"  {trans.get('annehmen','Annehmen')}: {it['accept']}")
        tlines.append(f"  {trans.get('ablehnen','Ablehnen')}: {it['reject']}")
        tlines.append("")
    body_text = "\n".join(tlines).strip()
    # HTML-Version (Inline-Styles für breite Kompatibilität)
    cards = []
    for it in items:
        guest_html = f"<div style='color:#6c757d;font-size:13px;margin-top:4px;'>{it['guest']}</div>" if it.get('guest') else ""
        cards.append(f"""
        <div style='border:1px solid #dee2e6;border-radius:8px;padding:12px;margin:10px 0;background:#ffffff;'>
          <div style='display:flex;justify-content:space-between;align-items:center;'>
            <div style='font-weight:700;font-size:16px'>{it['date']} · {it['apt']}</div>
            <span style='background:#0d6efd;color:#fff;border-radius:12px;padding:4px 8px;font-size:12px;'>{trans.get('zuweisung','Zuweisung')}</span>
          </div>
          <div style='margin-top:6px;font-size:14px;'>{it['desc']}</div>
          {guest_html}
          <div style='display:flex;gap:8px;margin-top:12px;'>
            <a href='{it['accept']}' style='text-decoration:none;background:#198754;color:#fff;padding:8px 10px;border-radius:6px;font-weight:600;'>{trans.get('annehmen','Annehmen')}</a>
            <a href='{it['reject']}' style='text-decoration:none;background:#dc3545;color:#fff;padding:8px 10px;border-radius:6px;font-weight:600;'>{trans.get('ablehnen','Ablehnen')}</a>
          </div>
        </div>
        """)
    body_html = f"""
    <div style='font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#f8f9fa;padding:16px;'>
      <div style='max-width:680px;margin:0 auto;'>
        <h2 style='margin:0 0 12px 0;font-size:20px;'>{trans.get('zuweisung','Zuweisung')} · {staff_name}</h2>
        {''.join(cards)}
        <div style='color:#6c757d;font-size:12px;margin-top:12px;'>
          {trans.get('hinweis','Hinweis') if 'hinweis' in trans else 'Hinweis'}: Diese E-Mail fasst Aufgaben der letzten 30 Minuten zusammen.
        </div>
      </div>
    </div>
    """
    return subject, body_text, body_html

def send_assignment_emails_job():
    base_url = BASE_URL.rstrip("/") or ""
    with SessionLocal() as db:
        pending = db.query(Task).filter(Task.assignment_status=="pending", Task.assigned_staff_id!=None, Task.assign_notified_at==None).all()
        if not pending:
            return []
        staff_ids = {t.assigned_staff_id for t in pending if t.assigned_staff_id}
        report = []
        for sid in staff_ids:
            staff = db.get(Staff, sid)
            if not staff or not (staff.email or "").strip():
                continue
            lang = (staff.language or "de")
            token = staff.magic_token
            tasks_for_staff = [t for t in pending if t.assigned_staff_id==sid]
            items = []
            trans = get_translations(lang)
            for t in tasks_for_staff:
                apt_name = ""
                if t.apartment_id:
                    apt = db.get(Apartment, t.apartment_id)
                    apt_name = apt.name if apt else ""
                guest_str = ""
                if t.booking_id:
                    b = db.get(Booking, t.booking_id)
                    if b:
                        gname = (b.guest_name or "").strip()
                        if gname:
                            guest_str = f"{gname}"
                        else:
                            # Adults/children fallback
                            ac = []
                            if b.adults:
                                ac.append(f"{trans.get('erw','Erw.')} {b.adults}")
                            if b.children:
                                ac.append(f"{trans.get('kinder','Kinder')} {b.children}")
                            guest_str = ", ".join(ac)
                desc = (t.notes or "").strip() or get_translations(lang).get('tätigkeit','Tätigkeit')
                accept_link = f"{base_url}/c/{token}/accept?task_id={t.id}"
                reject_link = f"{base_url}/c/{token}/reject?task_id={t.id}"
                # Berechne Gäste-Anzahl für Template
                guest_count = 0
                if t.booking_id:
                    b = db.get(Booking, t.booking_id)
                    if b:
                        guest_count = (b.adults or 0) + (b.children or 0)
                
                items.append({
                    'date': t.date,
                    'apt': apt_name,
                    'desc': desc,
                    'guest': guest_str,
                    'guest_count': guest_count,  # Für Template-Variable {{5}}
                    'accept': accept_link,
                    'reject': reject_link,
                })
            subject, body_text, body_html = build_assignment_email(lang, staff.name, items, base_url)
            _send_email(staff.email, subject, body_text, body_html)
            
            # WhatsApp-Benachrichtigung senden (falls Telefonnummer vorhanden)
            try:
                phone = getattr(staff, 'phone', None) or ""
                if phone and phone.strip():
                    log.info("📱 Sending WhatsApp to %s for staff %s (%d tasks)", phone, staff.name, len(items))
                    # Sende für jeden Task eine separate WhatsApp-Nachricht mit Template
                    for item in items:
                        item['staff_name'] = staff.name  # Füge staff_name zu item hinzu
                        template_vars = build_assignment_whatsapp_template_vars(item)
                        result = _send_whatsapp_with_opt_in(phone, template_vars, staff_id=sid, db=db)
                        if result:
                            log.info("✅ WhatsApp template sent to %s for task %s", phone, item.get('date', ''))
                        else:
                            log.warning("❌ WhatsApp template failed to %s for task %s", phone, item.get('date', ''))
                else:
                    log.debug("No phone number for staff %s, skipping WhatsApp", staff.name)
            except Exception as e:
                log.error("WhatsApp notification error for staff %s: %s", staff.name, e, exc_info=True)
            
            now = now_iso()
            for t in tasks_for_staff:
                t.assign_notified_at = now
            try:
                phone = getattr(staff, 'phone', None) or ""
            except:
                phone = ""
            report.append({
                'staff_name': staff.name,
                'email': staff.email,
                'phone': phone,
                'count': len(items),
                'items': items,
            })
        db.commit()
        return report

def send_whatsapp_for_existing_assignments():
    """Sende nur WhatsApp-Benachrichtigungen für bestehende Zuweisungen (auch wenn bereits per Email benachrichtigt)"""
    base_url = BASE_URL.rstrip("/") or ""
    with SessionLocal() as db:
        # Hole alle pending Tasks mit zugewiesenem Staff (auch wenn bereits benachrichtigt)
        pending = db.query(Task).filter(
            Task.assignment_status=="pending", 
            Task.assigned_staff_id!=None
        ).all()
        if not pending:
            return []
        staff_ids = {t.assigned_staff_id for t in pending if t.assigned_staff_id}
        report = []
        for sid in staff_ids:
            staff = db.get(Staff, sid)
            if not staff:
                continue
            # Prüfe ob Telefonnummer vorhanden ist
            phone = getattr(staff, 'phone', None) or ""
            if not phone or not phone.strip():
                log.debug("No phone number for staff %s, skipping WhatsApp", staff.name)
                continue
            
            lang = (staff.language or "de")
            token = staff.magic_token
            tasks_for_staff = [t for t in pending if t.assigned_staff_id==sid]
            items = []
            trans = get_translations(lang)
            for t in tasks_for_staff:
                apt_name = ""
                if t.apartment_id:
                    apt = db.get(Apartment, t.apartment_id)
                    apt_name = apt.name if apt else ""
                guest_str = ""
                if t.booking_id:
                    b = db.get(Booking, t.booking_id)
                    if b:
                        gname = (b.guest_name or "").strip()
                        if gname:
                            guest_str = f"{gname}"
                        else:
                            # Adults/children fallback
                            ac = []
                            if b.adults:
                                ac.append(f"{trans.get('erw','Erw.')} {b.adults}")
                            if b.children:
                                ac.append(f"{trans.get('kinder','Kinder')} {b.children}")
                            guest_str = ", ".join(ac)
                desc = (t.notes or "").strip() or get_translations(lang).get('tätigkeit','Tätigkeit')
                accept_link = f"{base_url}/c/{token}/accept?task_id={t.id}"
                reject_link = f"{base_url}/c/{token}/reject?task_id={t.id}"
                # Berechne Gäste-Anzahl für Template
                guest_count = 0
                if t.booking_id:
                    b = db.get(Booking, t.booking_id)
                    if b:
                        guest_count = (b.adults or 0) + (b.children or 0)
                
                items.append({
                    'date': t.date,
                    'apt': apt_name,
                    'desc': desc,
                    'guest': guest_str,
                    'guest_count': guest_count,  # Für Template-Variable {{5}}
                    'accept': accept_link,
                    'reject': reject_link,
                })
            
            # Nur WhatsApp senden (keine Email)
            try:
                log.info("📱 Sending WhatsApp to %s for staff %s (%d existing tasks)", phone, staff.name, len(items))
                # Sende für jeden Task eine separate WhatsApp-Nachricht mit Template
                for item in items:
                    item['staff_name'] = staff.name  # Füge staff_name zu item hinzu
                    template_vars = build_assignment_whatsapp_template_vars(item)
                    result = _send_whatsapp_with_opt_in(phone, template_vars, staff_id=sid, db=db)
                    if result:
                        log.info("✅ WhatsApp template sent to %s for task %s", phone, item.get('date', ''))
                    else:
                        log.warning("❌ WhatsApp template failed to %s for task %s", phone, item.get('date', ''))
            except Exception as e:
                log.error("WhatsApp notification error for staff %s: %s", staff.name, e, exc_info=True)
            
            report.append({
                'staff_name': staff.name,
                'phone': phone,
                'count': len(items),
                'items': items,
            })
        db.commit()
        return report
