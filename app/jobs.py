"""Background jobs and scheduled tasks"""
import json
import logging
import smtplib
from email.message import EmailMessage
from typing import Optional, List, Dict
from datetime import date as _date, datetime as _dt, timedelta as _td

from .db import SessionLocal
from .models import Booking, Staff, Apartment, Task, TaskSeries
from .services_smoobu import SmoobuClient
from .sync import upsert_tasks_from_bookings
from .config import BASE_URL, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, TWILIO_WHATSAPP_CONTENT_SID
from .utils import now_iso

log = logging.getLogger("smoobu")

# Helper functions (duplicated from main.py to avoid circular imports)
def _get_translations(lang: str) -> Dict[str, str]:
    """Get translations from helpers"""
    from .helpers import get_translations
    return get_translations(lang)

def _parse_date(s: str) -> _date | None:
    try:
        return _dt.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def _add_months(d: _date, months: int) -> _date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
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
        wd_map = {"mo":0,"tu":1,"we":2,"th":3,"fr":4,"sa":5,"su":6}
        if series.byweekday:
            wds = [wd_map.get(p.strip().lower()[:2]) for p in series.byweekday.split(",")]
            wds = [w for w in wds if w is not None]
            if not wds:
                wds = [s0.weekday()]
        else:
            wds = [s0.weekday()]
        start_week_monday = s0 - _td(days=s0.weekday())
        for d in _daterange_iter(max(start_from, s0), hard_until):
            windex = ((d - start_week_monday).days // 7)
            if windex % interval == 0 and d.weekday() in wds and d >= s0:
                out.append(d)
                if series.count and len(out) >= series.count:
                    break
    elif freq == "monthly":
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
        cur = s0
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
        if s0 >= start_from and s0 <= hard_until:
            out.append(s0)
    return out

def _send_email(to_email: str, subject: str, body_text: str, body_html: str | None = None):
    if not (SMTP_HOST and SMTP_FROM):
        log.warning("SMTP not configured, skipping email to %s", to_email)
        return
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

def _send_whatsapp(to_phone: str, message: str, use_template: bool = False):
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM):
        log.warning("Twilio not configured, skipping WhatsApp to %s", to_phone)
        return False
    if not to_phone or not to_phone.strip():
        log.warning("No phone number provided for WhatsApp")
        return False
    try:
        from twilio.rest import Client
        phone = to_phone.strip().replace(" ", "").replace("-", "")
        if not phone.startswith("+"):
            if phone.startswith("0"):
                phone = "+49" + phone[1:]
            else:
                phone = "+49" + phone
        whatsapp_to = f"whatsapp:{phone}"
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        log.info("📱 Sending WhatsApp: from=%s, to=%s, message_length=%d, use_template=%s", 
                 TWILIO_WHATSAPP_FROM, whatsapp_to, len(message), use_template)
        status_callback_url = None
        if BASE_URL:
            status_callback_url = f"{BASE_URL.rstrip('/')}/webhook/twilio/status"
        if use_template and TWILIO_WHATSAPP_CONTENT_SID:
            message_obj = client.messages.create(
                content_sid=TWILIO_WHATSAPP_CONTENT_SID,
                content_variables=json.dumps({"1": message}),
                from_=TWILIO_WHATSAPP_FROM,
                to=whatsapp_to,
                status_callback=status_callback_url
            )
            log.info("📱 Using WhatsApp template (Content SID: %s)", TWILIO_WHATSAPP_CONTENT_SID)
        else:
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
            return True
    except ImportError:
        log.error("Twilio library not installed. Install with: pip install twilio")
        return False
    except Exception as e:
        log.error("WhatsApp send failed to %s: %s", to_phone, e, exc_info=True)
        return False

def _send_whatsapp_with_opt_in(to_phone: str, message: str, staff_id: Optional[int] = None, db=None):
    opt_in_sent = False
    opt_in_confirmed = False
    if staff_id and db:
        staff = db.get(Staff, staff_id)
        if staff:
            opt_in_sent = getattr(staff, 'whatsapp_opt_in_sent', False)
            opt_in_confirmed = getattr(staff, 'whatsapp_opt_in_confirmed', False)
    if not opt_in_confirmed:
        if not opt_in_sent and TWILIO_WHATSAPP_CONTENT_SID:
            log.info("📱 Sending Opt-In message to %s (waiting for confirmation)", to_phone)
            opt_in_message = "Willkommen! Du erhältst ab jetzt Benachrichtigungen über neue Aufgaben."
            opt_in_result = _send_whatsapp(to_phone, opt_in_message, use_template=True)
            if opt_in_result and staff_id and db:
                staff = db.get(Staff, staff_id)
                if staff:
                    staff.whatsapp_opt_in_sent = True
                    db.commit()
                    log.info("✅ Opt-In message sent to staff %d (waiting for confirmation)", staff_id)
            return opt_in_result
        else:
            log.info("📱 Opt-In already sent to %s, waiting for confirmation before sending normal message", to_phone)
            return False
    log.info("📱 Opt-In confirmed for %s, sending normal message", to_phone)
    return _send_whatsapp(to_phone, message, use_template=False)

def build_assignment_whatsapp_message(lang: str, staff_name: str, items: list, base_url: str) -> str:
    trans = _get_translations(lang)
    msg = f"*{trans.get('zuweisung', 'Zuweisung')} · {staff_name}*\n\n"
    for i, it in enumerate(items, 1):
        msg += f"*{i}. {it['apt']}* - {it['date']}\n"
        if it['guest']:
            msg += f"👤 {it['guest']}\n"
        msg += f"📝 {it['desc']}\n"
        msg += f"✅ {it['accept']}\n"
        msg += f"❌ {it['reject']}\n\n"
    return msg

def build_assignment_email(lang: str, staff_name: str, items: list, base_url: str) -> tuple[str, str, str]:
    trans = _get_translations(lang)
    subject = f"{trans.get('zuweisung','Zuweisung')}: {len(items)} {trans.get('tasks','Tasks')}"
    tlines = [f"{trans.get('team','Team')}: {staff_name}", ""]
    for it in items:
        tlines.append(f"- {it['date']}: {it['desc']} ({it['apt']})")
        if it.get('guest'):
            tlines.append(f"  {it['guest']}")
        tlines.append(f"  {trans.get('annehmen','Annehmen')}: {it['accept']}")
        tlines.append(f"  {trans.get('ablehnen','Ablehnen')}: {it['reject']}")
        tlines.append("")
    body_text = "\n".join(tlines).strip()
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

def _daterange(days=60):
    import datetime as dt
    start = dt.date.today()
    end = start + dt.timedelta(days=days)
    return start.isoformat(), end.isoformat()

def _best_guest_name(it: dict) -> str:
    guest = it.get("guest") or {}
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
    adults = it.get("adults") or 0
    children = it.get("children") or 0
    if adults > 0 or children > 0:
        parts = []
        if adults > 0:
            parts.append(f"{adults} Erw.")
        if children > 0:
            parts.append(f"{children} Kind" + ("er" if children > 1 else ""))
        return ", ".join(parts)
    return ""

# Job functions
async def refresh_bookings_job():
    """Refresh bookings from Smoobu API"""
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
                try:
                    log.warning("⚠️ No guest name in booking %d. Available keys: %s", b_id, list(it.keys()))
                    if it.get("guest"):
                        log.warning("⚠️ guest keys: %s", list((it.get("guest") or {}).keys()))
                    if it.get("contact"):
                        log.warning("⚠️ contact keys: %s", list((it.get("contact") or {}).keys()))
                    log.warning("⚠️ adults=%s children=%s guests=%s", it.get("adults"), it.get("children"), it.get("guests"))
                except Exception:
                    pass
                guest_name = _guest_count_label(it) or ""
            arrival = (it.get("arrival") or "")[:10]
            departure = (it.get("departure") or "")[:10]

            is_blocked = it.get("isBlockedBooking", False) or it.get("blocked", False)
            status = it.get("status", "").lower() if it.get("status") else ""
            cancelled = status == "cancelled" or it.get("cancelled", False)
            is_internal = it.get("isInternal", False)
            is_draft = status == "draft"
            is_pending = status == "pending"
            is_on_hold = status == "on hold" or status == "on_hold"
            
            booking_type = it.get("type", "").lower()
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
                try:
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
                        trans = _get_translations(lang)
                        items_list = []
                        for t in tlist:
                            token = staff.magic_token
                            items_list.append({
                                'date': t.date,
                                'apt': apt_name or "",
                                'desc': (t.notes or "").strip() or trans.get('tätigkeit','Tätigkeit'),
                                'link': f"{BASE_URL.rstrip('/')}/cleaner/{token}",
                            })
                        subject = f"{trans.get('cleanup','Bereinigen')}: {trans.get('zuweisung','Zuweisung')} storniert"
                        lines = [f"{trans.get('zuweisung','Zuweisung')} storniert:"]
                        for it in items_list:
                            lines.append(f"- {it['date']} · {it['apt']} · {it['desc']}")
                        lines.append("")
                        lines.append(items_list[0]['link'])
                        body_text = "\n".join(lines)
                        cards = []
                        for it in items_list:
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
                              <a href='{items_list[0]['link']}' style='text-decoration:none;background:#0d6efd;color:#fff;padding:8px 10px;border-radius:6px;font-weight:600;'>Zur Übersicht</a>
                            </div>
                          </div>
                        </div>
                        """
                        _send_email(staff.email, subject, body_text, body_html)
                except Exception as e:
                    log.error("Error sending cancellation notifications for booking %d: %s", b_id, e)
                b_existing = db.get(Booking, b_id)
                if b_existing:
                    db.delete(b_existing)
                    log.info("🗑️ Deleted existing booking %d from database", b_id)
                for t in db.query(Task).filter(Task.booking_id==b_id).all():
                    db.delete(t)
                db.commit()
                continue
            
            seen_booking_ids.append(b_id)
            if apt_id:
                seen_apartment_ids.append(apt_id)
            
            b_existing = db.get(Booking, b_id)
            if b_existing:
                b_existing.apartment_id = apt_id
                b_existing.apartment_name = apt_name
                b_existing.arrival = arrival
                b_existing.departure = departure
                b_existing.guest_name = guest_name
                b_existing.adults = it.get("adults")
                b_existing.children = it.get("children")
                b_existing.guest_comments = (it.get("guestComments") or it.get("guest_comments") or "")[:2000]
            else:
                db.add(Booking(
                    id=b_id,
                    apartment_id=apt_id,
                    apartment_name=apt_name,
                    arrival=arrival,
                    departure=departure,
                    guest_name=guest_name,
                    adults=it.get("adults"),
                    children=it.get("children"),
                    guest_comments=(it.get("guestComments") or it.get("guest_comments") or "")[:2000]
                ))
        
        db.commit()
        all_bookings = db.query(Booking).all()
        upsert_tasks_from_bookings(all_bookings)
        
        removed = 0
        for t in db.query(Task).all():
            if not t.date or not t.date.strip():
                db.delete(t); removed += 1
        if removed:
            log.info("🧹 Cleanup: %d Tasks ohne Datum entfernt.", removed)
        db.commit()
        log.info("✅ Refresh completed successfully")

def expand_series_job(days_ahead: int = 30):
    """Generate tasks from active TaskSeries for the next days_ahead."""
    with SessionLocal() as db:
        horizon = _date.today() + _td(days=days_ahead)
        series_list = db.query(TaskSeries).filter(TaskSeries.active==True).all()
        created = 0
        new_tasks: list[Task] = []
        for ser in series_list:
            last = db.query(Task).filter(Task.series_id==ser.id).order_by(Task.date.desc()).first()
            start_from = _parse_date(last.date) + _td(days=1) if last else _parse_date(ser.start_date) or _date.today()
            occ = _expand_series_occurrences(ser, start_from, horizon)
            for d in occ:
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
        if created > 0:
            try:
                send_assignment_emails_job()
            except Exception as e:
                log.error("send_assignment_emails_job after series expansion failed: %s", e)
        log.info("🗓️ Series expansion created %d tasks up to %s", created, horizon.isoformat())
        return created

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
            trans = _get_translations(lang)
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
                            ac = []
                            if b.adults:
                                ac.append(f"{trans.get('erw','Erw.')} {b.adults}")
                            if b.children:
                                ac.append(f"{trans.get('kinder','Kinder')} {b.children}")
                            guest_str = ", ".join(ac)
                desc = (t.notes or "").strip() or _get_translations(lang).get('tätigkeit','Tätigkeit')
                accept_link = f"{base_url}/c/{token}/accept?task_id={t.id}"
                reject_link = f"{base_url}/c/{token}/reject?task_id={t.id}"
                items.append({
                    'date': t.date,
                    'apt': apt_name,
                    'desc': desc,
                    'guest': guest_str,
                    'accept': accept_link,
                    'reject': reject_link,
                })
            subject, body_text, body_html = build_assignment_email(lang, staff.name, items, base_url)
            _send_email(staff.email, subject, body_text, body_html)
            
            try:
                phone = getattr(staff, 'phone', None) or ""
                if phone and phone.strip():
                    log.info("📱 Sending WhatsApp to %s for staff %s (%d tasks)", phone, staff.name, len(items))
                    whatsapp_msg = build_assignment_whatsapp_message(lang, staff.name, items, base_url)
                    result = _send_whatsapp_with_opt_in(phone, whatsapp_msg, staff_id=sid, db=db)
                    if result:
                        log.info("✅ WhatsApp queued/sent to %s (staff: %s) - Delivery status will be logged via webhook", phone, staff.name)
                    else:
                        log.warning("❌ WhatsApp send failed to %s (staff: %s) - check logs above for details", phone, staff.name)
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
            phone = getattr(staff, 'phone', None) or ""
            if not phone or not phone.strip():
                log.debug("No phone number for staff %s, skipping WhatsApp", staff.name)
                continue
            
            lang = (staff.language or "de")
            token = staff.magic_token
            tasks_for_staff = [t for t in pending if t.assigned_staff_id==sid]
            items = []
            trans = _get_translations(lang)
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
                            ac = []
                            if b.adults:
                                ac.append(f"{trans.get('erw','Erw.')} {b.adults}")
                            if b.children:
                                ac.append(f"{trans.get('kinder','Kinder')} {b.children}")
                            guest_str = ", ".join(ac)
                desc = (t.notes or "").strip() or _get_translations(lang).get('tätigkeit','Tätigkeit')
                accept_link = f"{base_url}/c/{token}/accept?task_id={t.id}"
                reject_link = f"{base_url}/c/{token}/reject?task_id={t.id}"
                items.append({
                    'date': t.date,
                    'apt': apt_name,
                    'desc': desc,
                    'guest': guest_str,
                    'accept': accept_link,
                    'reject': reject_link,
                })
            
            try:
                log.info("📱 Sending WhatsApp to %s for staff %s (%d existing tasks)", phone, staff.name, len(items))
                whatsapp_msg = build_assignment_whatsapp_message(lang, staff.name, items, base_url)
                result = _send_whatsapp_with_opt_in(phone, whatsapp_msg, staff_id=sid, db=db)
                if result:
                    log.info("✅ WhatsApp queued/sent to %s (staff: %s) - Delivery status will be logged via webhook", phone, staff.name)
                else:
                    log.warning("❌ WhatsApp send failed to %s (staff: %s) - check logs above for details", phone, staff.name)
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

