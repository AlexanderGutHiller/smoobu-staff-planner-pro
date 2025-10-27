from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
async def root():
    return "<h1>Smoobu Staff Planner</h1><p>Willkommen zur Einsatzplanung!</p>"