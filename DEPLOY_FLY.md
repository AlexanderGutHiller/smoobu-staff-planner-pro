## Deployment auf Fly.io

Diese Anleitung beschreibt das Deployment dieser App auf Fly.io mit Dockerfile, persistentem Volume (SQLite) und den nötigen Umgebungsvariablen.

### Voraussetzungen
- Flyctl installiert und eingeloggt
- Docker lokal optional (Build erfolgt bei Fly)

```bash
# Login
fly auth login

# Aktuellen Account prüfen
fly accounts list
```

### 1) App konfigurieren
- In `fly.toml` muss die App-ID mit eurer App übereinstimmen:
  - `app = "smoobu-staff-planner-pro-ibg5yw"` (bei Bedarf anpassen)
- Der Service lauscht auf Port 8000, Health-Check unter `/health`.
- Persistent Storage ist nach `[[mounts]]` auf `/app/data` gemountet.

### 2) Volume anlegen (Persistent Storage)
Die SQLite-Datenbank liegt im Container unter `/app/data/data.db`. Legt dafür ein Volume in eurer Region an (hier: `fra`).

```bash
# Einmalig anlegen (Größe 3GB; Name muss mit fly.toml übereinstimmen)
fly volumes create smoobu_data \
  --region fra \
  --size 3

# Vorhandene Volumes anzeigen
fly volumes list -a smoobu-staff-planner-pro-ibg5yw
```

Hinweis: Für eine einzelne App-Instanz genügt genau EIN Volume in der Ziel-Region.

### 3) Secrets setzen (Umgebungsvariablen)
Die App erwartet folgende Variablen:
- `ADMIN_TOKEN` (erforderlich für Admin-Login)
- `SMOOBU_API_KEY` (Smoobu-API)
- `BASE_URL` (öffentliche Basis-URL eurer App, z. B. `https://<app>.fly.dev`)
- `TIMEZONE` (z. B. `Europe/Berlin`)
- SMTP (optional, für Mails): `SMTP_HOST`, `SMTP_PORT` (z. B. 587), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`

```bash
fly secrets set \
  ADMIN_TOKEN=... \
  SMOOBU_API_KEY=... \
  BASE_URL=https://smoobu-staff-planner-pro-ibg5yw.fly.dev \
  TIMEZONE=Europe/Berlin \
  SMTP_HOST=... SMTP_PORT=587 SMTP_USER=... SMTP_PASSWORD=... SMTP_FROM=...
```

Optional könnt ihr `DATA_DIR`/`DB_PATH` setzen. Ohne diese Variablen nutzt die App automatisch `/app/data/data.db` (das gemountete Volume).

### 4) Deploy
Die App nutzt ein Dockerfile. Deployment:

```bash
# Validieren
fly validate

# Deploy (nutzt Dockerfile)
fly deploy -a smoobu-staff-planner-pro-ibg5yw
```

Logs/Status prüfen:
```bash
fly logs -a smoobu-staff-planner-pro-ibg5yw
fly status -a smoobu-staff-planner-pro-ibg5yw
```

### 5) Wichtige Endpunkte
- Admin-UI: `/admin/<ADMIN_TOKEN>`
- Health: `/health`
- Import jetzt: `/admin/<ADMIN_TOKEN>/import`
- Zuweisungs-Mails senden (Manuell): `/admin/<ADMIN_TOKEN>/notify_assignments`

### 6) Rollouts ohne Datenverlust
Die Daten liegen auf dem Volume `smoobu_data`. Bei Neu-Deployments bleibt das Volume bestehen. Wichtig:
- Startet nicht mehrere Maschinen in derselben Region, die dasselbe Volume benötigen.
- Löscht ein Volume nur, wenn ihr die Daten bewusst verwerfen wollt.

### 7) Häufige Fehler
- „needs volumes with name 'smoobu_data'“: Volume fehlt in Region → mit `fly volumes create` anlegen.
- „http_checks already exists“: In `fly.toml` keine doppelte Health-Check Konfiguration; nutzt `[[http_service.checks]]`.
- Kein Admin-Zugriff: `ADMIN_TOKEN` als Secret setzen.
- Mails kommen nicht: SMTP-Settings prüfen (`SMTP_HOST`, `SMTP_FROM`, ggf. Auth) und Logs ansehen.

### 8) Skalierung
Standardmäßig läuft 1 Maschine (siehe `min_machines_running = 1`). Mehr Instanzen sind mit SQLite/Single-Volume nicht empfohlen. Wenn ihr skaliert, braucht ihr eine zentrale Datenbank (z. B. Postgres) oder sharded Volumes, was diese App aktuell nicht vorsieht.

### 9) Region/Umzug
Wenn ihr die Region ändern wollt, müsst ihr ein neues Volume in der Zielregion anlegen, Daten migrieren und die App dorthin deployen. Ein Volume ist immer an eine Region gebunden.

—
Stand: v6.3 – Dockerfile-basiertes Deployment, SQLite auf Fly-Volume, Health-Check `/health`.

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

