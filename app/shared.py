"""Shared objects across the application"""
from fastapi.templating import Jinja2Templates
from .config import APP_VERSION, APP_BUILD_DATE
import datetime as dt

# Templates
templates = Jinja2Templates(directory="app/templates")
templates.env.globals.update({
    "APP_VERSION": APP_VERSION,
    "APP_BUILD_DATE": APP_BUILD_DATE,
    "APP_VERSION_DISPLAY": f"Version {APP_VERSION} · {APP_BUILD_DATE}",
    "dt": dt,
})

