# Fly.io Deployment Guide

## Erste Einrichtung

### 1. Volumes erstellen (einmalig)

Die App benötigt ein persistentes Volume für die SQLite-Datenbank, damit Daten bei Deployments nicht verloren gehen.

```bash
# Erstelle das Volume (ersetzt APP_NAME mit deinem App-Namen)
fly volumes create smoobu_data \
  -a smoobu-staff-planner-pro-ibg5yw \
  --size 3 \
  --region fra

# Falls 2 Volumes benötigt werden (bei mehreren Instanzen):
fly volumes create smoobu_data \
  -a smoobu-staff-planner-pro-ibg5yw \
  --size 3 \
  --region fra
```

### 2. Secrets/Environment Variables setzen

```bash
fly secrets set \
  ADMIN_TOKEN="dein-admin-token" \
  SMOOBU_API_KEY="deine-api-key" \
  SMOOBU_BASE_URL="https://login.smoobu.com/api" \
  BASE_URL="https://deine-app.fly.dev" \
  REFRESH_INTERVAL_MINUTES="60" \
  TIMEZONE="Europe/Berlin" \
  -a smoobu-staff-planner-pro-ibg5yw
```

### 3. Deployen

```bash
fly deploy -a smoobu-staff-planner-pro-ibg5yw
```

## Wichtige Hinweise

- **Volumes müssen VOR dem ersten Deploy erstellt werden** (sonst Fehler)
- Die App erkennt automatisch, ob `/app/data` existiert und verwendet es
- Wenn kein Volume vorhanden ist, speichert die App lokal (Daten gehen bei Deployments verloren!)

## Volumes prüfen

```bash
# Liste aller Volumes
fly volumes list -a smoobu-staff-planner-pro-ibg5yw

# Status der App
fly status -a smoobu-staff-planner-pro-ibg5yw
```

