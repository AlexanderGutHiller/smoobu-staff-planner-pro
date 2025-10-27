# Smoobu Staff Planner (v5)

FastAPI-App für Reinigungs-/Einsatzplanung mit Smoobu-Sync (Delta/Upsert) und "Next Arrival"-Infos.

## Start (lokal)

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 10000 --reload
```

## Environment

- `SMOOBU_API_KEY` (erforderlich)
- `SMOOBU_BASE_URL` (default: https://login.smoobu.com/api)
- `REFRESH_INTERVAL_MINUTES` (default: 60)
- `TIMEZONE` (default: Europe/Berlin)
- `ADMIN_TOKEN` (für Admin-UI)

## Hinweise
- SQLite DB: `./data.db`
- Admin UI: `/admin/<ADMIN_TOKEN>`
- Cleaner Portal: `/cleaner/<MAGIC_TOKEN>`
