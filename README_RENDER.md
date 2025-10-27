
# Smoobu Staff Planner — Render-only Package (v4)

- Fix: UNIQUE constraint for apartments by using a local cache + session.flush().
- Still uses Smoobu API base `https://login.smoobu.com/api` and `/reservations` endpoint.

Deploy on Render:
- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port 10000`
- PORT: `10000`

ENV:
- `SMOOBU_API_KEY`
- `SMOOBU_BASE_URL` = `https://login.smoobu.com/api`
- `REFRESH_INTERVAL_MINUTES` = `60`
- `TIMEZONE` = `Europe/Berlin`
- `ADMIN_TOKEN`
