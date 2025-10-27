from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("placeholder.html", {"request": request})

@app.get("/admin/{admin_id}", response_class=HTMLResponse)
async def admin_dashboard(request: Request, admin_id: int):
    return templates.TemplateResponse("admin_dashboard.html", {"request": request, "admin_id": admin_id})