
# Smoobu Staff Planner — Render-only Package (v8.2)

Includes:
- v8 features (guest counts for next arrival in admin & cleaner, mobile timer, multi-language de/en/bg/ro/ru, readable extras)
- Hotfix: adds `TimeLog` model (fixes ImportError)

Render settings:
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn app.main:app --host 0.0.0.0 --port 10000`
- Env: `SMOOBU_API_KEY`, `SMOOBU_BASE_URL=https://login.smoobu.com/api`, `ADMIN_TOKEN`, `DEFAULT_TASK_START=11:00` (optional)
