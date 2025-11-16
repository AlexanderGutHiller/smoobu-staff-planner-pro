"""General routes (root, health, language, service worker)"""
from fastapi import APIRouter, Response
from fastapi.responses import RedirectResponse, HTMLResponse
from ..utils import now_iso

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
async def root():
    return "<html><head><link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' rel='stylesheet'></head><body class='p-4' style='font-family:system-ui;'><h1>Smoobu Staff Planner Pro</h1><p>Service läuft. Admin-UI: <code>/admin/&lt;ADMIN_TOKEN&gt;</code></p><p>Health: <a href='/health'>/health</a></p></body></html>"

@router.get("/health")
async def health():
    return {"ok": True, "time": now_iso()}

@router.get("/set-language")
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

@router.get("/sw.js")
async def service_worker():
    """Service Worker für Web Push Notifications"""
    try:
        with open("static/sw.js", "rb") as f:
            return Response(f.read(), media_type="application/javascript")
    except Exception:
        return Response("// no service worker", media_type="application/javascript")

