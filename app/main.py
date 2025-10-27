
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/")
async def root():
    return {"message": "Smoobu Staff Planner ready"}

@app.get("/admin/132576781", response_class=HTMLResponse)
async def admin_home(request: Request):
    return templates.TemplateResponse("admin_home.html", {"request": request})
