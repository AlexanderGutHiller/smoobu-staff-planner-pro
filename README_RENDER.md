
# Smoobu Staff Planner — Render-only Package (v3)

**Fix:** Use official Smoobu API base + endpoint (`/reservations?from=&to=`).

Deploy on Render (Python runtime):
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn app.main:app --host 0.0.0.0 --port 10000`
- PORT: `10000`

Environment Variables:
- `SMOOBU_API_KEY` (required)
- `SMOOBU_BASE_URL` = `https://login.smoobu.com/api`  ← **NEW**
- `REFRESH_INTERVAL_MINUTES` = `60` (change for testing)
- `TIMEZONE` = `Europe/Berlin`
- `ADMIN_TOKEN` (choose a long token)

Admin:
- `/admin/<ADMIN_TOKEN>`
- Manual import: `/admin/<ADMIN_TOKEN>/import`
