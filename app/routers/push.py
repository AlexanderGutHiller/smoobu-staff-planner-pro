"""Web Push routes"""
import json
import logging
from typing import Optional
from fastapi import APIRouter, Request, Depends, Form, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session
from pywebpush import webpush, WebPushException

from ..dependencies import get_db, _is_admin_token
from ..config import VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_EMAIL, ADMIN_TOKEN
from ..models import Staff, PushSubscription
from ..utils import now_iso
from ..main import log

router = APIRouter(tags=["push"])



# Push Routes
router_admin = APIRouter(prefix="/admin/{token}", tags=["push"])


# GET /push/public_key -> /push/public_key
@router.get("/push/public_key")
async def push_public_key():
    if not VAPID_PUBLIC_KEY:
        return JSONResponse({"publicKey": ""})
    return JSONResponse({"publicKey": VAPID_PUBLIC_KEY})



# POST /push/subscribe -> /push/subscribe
@router.post("/push/subscribe")
async def push_subscribe(request: Request, staff_token: Optional[str] = Query(None), db=Depends(get_db)):
    data = await request.json()
    endpoint = data.get("endpoint")
    keys = data.get("keys", {})
    p256dh = keys.get("p256dh", "")
    auth = keys.get("auth", "")
    if not endpoint or not p256dh or not auth:
        raise HTTPException(status_code=400, detail="Invalid subscription")
    staff_id = None
    if staff_token:
        s = db.query(Staff).filter(Staff.magic_token==staff_token).first()
        if s: staff_id = s.id
    # deduplicate
    existing = db.query(PushSubscription).filter(PushSubscription.endpoint==endpoint).first()
    ua = request.headers.get("user-agent", "")[:250]
    now = now_iso()
    if existing:
        existing.p256dh = p256dh
        existing.auth = auth
        existing.user_agent = ua
        if staff_id: existing.staff_id = staff_id
    else:
        sub = PushSubscription(staff_id=staff_id, endpoint=endpoint, p256dh=p256dh, auth=auth, user_agent=ua, created_at=now)
        db.add(sub)
    db.commit()
    return JSONResponse({"ok": True})



# POST /push/unsubscribe -> /push/unsubscribe
@router.post("/push/unsubscribe")
async def push_unsubscribe(request: Request, db=Depends(get_db)):
    data = await request.json()
    endpoint = data.get("endpoint")
    if not endpoint:
        raise HTTPException(status_code=400, detail="Missing endpoint")
    sub = db.query(PushSubscription).filter(PushSubscription.endpoint==endpoint).first()
    if sub:
        db.delete(sub)
        db.commit()
    return JSONResponse({"ok": True})

def _send_webpush_to_subscription(sub: PushSubscription, payload: dict):
    if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
        log.warning("WebPush disabled: missing VAPID keys")
        return False
    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_EMAIL},
            ttl=60,
        )
        return True
    except WebPushException as e:
        log.warning("WebPush failed: %s", e)
        return False



# POST /admin/{token}/push/test -> /push/test
@router_admin.post("/push/test")
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

