# Deployment auf Fly.io

Diese Anleitung beschreibt das Deployment dieser App auf Fly.io. Es gibt zwei App-Instanzen:
- **Test**: `smoobu-staff-planner-pro-ibg5yw` (aus `fly.toml`)
- **Live**: `staffplanner-live` (aus `fly.live.toml`)

Beide Apps nutzen dasselbe GitHub-Repo, haben aber separate Volumes und Secrets.

## Voraussetzungen
- Flyctl installiert und eingeloggt
- Docker lokal optional (Build erfolgt bei Fly)

```bash
# Login
fly auth login

# Aktuellen Account prüfen
fly accounts list
```

## Setup für Test-App (smoobu-staff-planner-pro-ibg5yw)

### 1) Volume anlegen
```bash
fly volumes create smoobu_data \
  -a smoobu-staff-planner-pro-ibg5yw \
  --region fra \
  --size 3
```

### 2) Secrets setzen
```bash
fly secrets set \
  ADMIN_TOKEN=... \
  SMOOBU_API_KEY=... \
  BASE_URL=https://smoobu-staff-planner-pro-ibg5yw.fly.dev \
  TIMEZONE=Europe/Berlin \
  SMTP_HOST=... SMTP_PORT=587 SMTP_USER=... SMTP_PASSWORD=... SMTP_FROM=... \
  -a smoobu-staff-planner-pro-ibg5yw
```

### 3) Deploy
```bash
fly deploy -a smoobu-staff-planner-pro-ibg5yw
```

## Setup für Live-App (staffplanner-live)

### 1) Volume anlegen
```bash
fly volumes create staffplanner_live_data \
  -a staffplanner-live \
  --region fra \
  --size 3
```

### 2) Secrets setzen
```bash
fly secrets set \
  ADMIN_TOKEN=... \
  SMOOBU_API_KEY=... \
  BASE_URL=https://staffplanner-live.fly.dev \
  TIMEZONE=Europe/Berlin \
  SMTP_HOST=... SMTP_PORT=587 SMTP_USER=... SMTP_PASSWORD=... SMTP_FROM=... \
  -a staffplanner-live
```

### 3) Manuelles Deploy
```bash
# Wichtig: Nutze die Live-Konfiguration
fly deploy -a staffplanner-live --config fly.live.toml
```

**Hinweis**: Die Live-App sollte nur manuell deployed werden (keine automatischen Deploys).

## Wichtige Befehle

### Logs ansehen
```bash
# Test-App
fly logs -a smoobu-staff-planner-pro-ibg5yw

# Live-App
fly logs -a staffplanner-live
```

### Status prüfen
```bash
# Test-App
fly status -a smoobu-staff-planner-pro-ibg5yw

# Live-App
fly status -a staffplanner-live
```

### Volumes anzeigen
```bash
# Test-App
fly volumes list -a smoobu-staff-planner-pro-ibg5yw

# Live-App
fly volumes list -a staffplanner-live
```

## Wichtige Endpunkte
- Admin-UI: `/admin/<ADMIN_TOKEN>`
- Health: `/health`
- Import jetzt: `/admin/<ADMIN_TOKEN>/import`
- Zuweisungs-Mails senden: `/admin/<ADMIN_TOKEN>/notify_assignments`

## Unterschiede zwischen Test und Live

| Feature | Test-App | Live-App |
|---------|----------|----------|
| App-Name | `smoobu-staff-planner-pro-ibg5yw` | `staffplanner-live` |
| Config-Datei | `fly.toml` | `fly.live.toml` |
| Volume | `smoobu_data` | `staffplanner_live_data` |
| Deploy | Automatisch (wenn konfiguriert) | Nur manuell |
| URL | `https://smoobu-staff-planner-pro-ibg5yw.fly.dev` | `https://staffplanner-live.fly.dev` |

## Rollouts ohne Datenverlust
- Die Daten liegen auf den Volumes (`smoobu_data` bzw. `staffplanner_live_data`)
- Bei Neu-Deployments bleiben die Volumes bestehen
- **Wichtig**: Startet nicht mehrere Maschinen in derselben Region, die dasselbe Volume benötigen

## Häufige Fehler
- **"needs volumes with name 'X'"**: Volume fehlt → mit `fly volumes create` anlegen
- **"http_checks already exists"**: Doppelte Health-Check Konfiguration → nutzt `[[http_service.checks]]`
- **Kein Admin-Zugriff**: `ADMIN_TOKEN` als Secret setzen
- **Mails kommen nicht**: SMTP-Settings prüfen und Logs ansehen

## GitHub Integration
- Beide Apps können vom selben GitHub-Repo gespeist werden
- **Test-App**: Kann automatische Deploys haben (optional)
- **Live-App**: Sollte nur manuelle Deploys haben
  - Nutze `fly deploy -a staffplanner-live --config fly.live.toml` für manuelle Deploys

---
Stand: v6.3 – Zwei App-Instanzen (Test/Live), Dockerfile-basiertes Deployment, SQLite auf Fly-Volumes