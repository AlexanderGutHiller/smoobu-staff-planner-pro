
# Smoobu Staff Planner — Render-only Package

## Deploy on Render (Python runtime)
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn app.main:app --host 0.0.0.0 --port 10000`
- PORT env: set to `10000` in Render service
- Set Environment Variables in Render Dashboard:
  - `SMOOBU_API_KEY` (required for importing bookings)
  - `SMOOBU_BASE_URL` = `https://api.smoobu.com/api/v1`
  - `REFRESH_INTERVAL_MINUTES` = `60`
  - `TIMEZONE` = `Europe/Berlin`
  - `ADMIN_TOKEN` (choose a long random token)

Admin URL pattern: `/admin/<ADMIN_TOKEN>`
Root `/` responds 200 "OK" to help with health checks.
