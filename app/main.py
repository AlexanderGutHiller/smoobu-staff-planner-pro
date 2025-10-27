
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Service läuft"}

@app.get("/admin/{admin_id}")
def get_admin_dashboard(admin_id: int):
    return {"admin_id": admin_id, "message": "Admin-Dashboard ist noch leer"}
