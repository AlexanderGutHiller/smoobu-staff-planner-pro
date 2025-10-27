
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.importer import import_from_smoobu  # Re-add the import function
from app.templates import render_admin_dashboard

app = FastAPI()

@app.get("/")
async def root():
    return HTMLResponse("<h1>Smoobu Staff Planner</h1><p>Willkommen!</p>")

@app.get("/admin/{admin_id}")
async def admin_dashboard(admin_id: int):
    html = render_admin_dashboard(admin_id)
    return HTMLResponse(content=html)

@app.get("/admin/{admin_id}/import")
async def import_data(admin_id: int):
    await import_from_smoobu(admin_id)
    return RedirectResponse(url=f"/admin/{admin_id}", status_code=303)
