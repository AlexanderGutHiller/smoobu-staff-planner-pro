# Smoobu Staff Render v6.3

Ein vollautomatisiertes System zur Verwaltung von Reinigungsvorgängen für Apartments basierend auf Smoobu-Buchungsdaten.

## 🎯 Zweck

Verwaltung von Reinigungsvorgängen pro Apartment mit Planung, Echtzeitstatus und Auswertung (Lohnkosten, Arbeitszeiten).

## 🏗️ Architektur

### Technologie-Stack
- **Backend**: FastAPI (Python)
- **Frontend**: Jinja2 Templates + AJAX / JavaScript
- **Datenbank**: SQLite mit SQLAlchemy ORM
- **Hosting**: Render Cloud
- **Scheduler**: APScheduler für automatisierte Synchronisation

### Datenmodelle
- **Bookings**: Buchungsdaten aus Smoobu
- **Apartments**: Apartment-Konfiguration (Name, Standarddauer, Preis, Max-Stunden)
- **Staff**: Reinigungskräfte (Name, Stundensatz, Max-Stunden/Monat, Magic Token)
- **Tasks**: Reinigungstasks (Datum, Dauer, Status, Zuweisung, Lock)
- **TimeLog**: Zeitaufzeichnungen pro Task (Start, Stop, Ist-Minuten)

---

## 🔄 Smoobu-Integration & Automatisierung

### Automatische Synchronisation
- **Interval**: Alle 60 Minuten (konfigurierbar via `REFRESH_INTERVAL_MINUTES`)
- **Datumsbereich**: 60 Tage im Voraus
- **Sync-Logik**:
  - Import aller Buchungen aus Smoobu
  - Automatische Task-Generierung:
    - **Anreisedatum** → nächste Reinigung
    - **Abreisedatum** → Reinigungstag
    - Gastname wird übernommen
  - Stornierte Buchungen: zugehörige Tasks werden automatisch gelöscht
  - Fehlerprüfung: Apartments ohne Abreise werden gefiltert

### Manuelle Synchronisation
Optional über "Jetzt neu synchronisieren"-Button im Admin-Dashboard.

### Task-Hashing
Jeder Task hat einen `booking_hash` zur Identifikation und Vermeidung von Duplikaten.

---

## 👩‍💼 Admin-Dashboard

Zugriff: `/admin/{ADMIN_TOKEN}`

### Funktionen

#### Apartment-Management (`/admin/{token}/apartments`)
- Pflege von:
  - Apartmentname
  - Standarddauer pro Reinigung (in Minuten)
- Dieser Wert wird automatisch in neue Tasks übernommen

#### Task-Übersicht (`/admin/{token}`)
- **Spalten**:
  - Datum (mit deutschem Format + Wochentag)
  - Apartment (mit Gastname)
  - Geplante Dauer
  - Nächste Anreise (inkl. Gästeanzahl)
  - Zugeordneter Mitarbeiter (MA)
  - Lock-Status
  - Task-ID
  - Notizen
- **Filter**:
  - Datum (z.B. "2025-10")
  - Apartment/Gast/Notiz (Textsuche)
  - Staff (Dropdown)

#### Team-Management (`/admin/{token}/staff`)
- Anlegen neuer Mitarbeiter:
  - Name
  - Stundensatz (€/Std)
  - Maximale Stunden pro Monat
- Anzeige des Magic-Links (kopierbar)
- Aktivieren/Deaktivieren

#### Task-Zuweisung
- Pro Task Staff-Mitglied zuordnen
- Lock-Funktion (gesperrte Tasks werden bei automatischer Synchronisation nicht überschrieben)

#### Manuelle Aktionen
- **"Import jetzt"**: Sofortiger Smoobu-Sync
- Filter verändert sich per AJAX (keine Seite-Reloads)

---

## 👷 Reinigungskraft-Ansicht (Cleaner View)

Zugriff: `/cleaner/{MAGIC_TOKEN}`

### Features

#### Übersicht
- Liste aller zugewiesenen Apartments mit:
  - Datum + Wochentag
  - Apartmentname
  - Gastname (klein, grau unter dem Apartmentnamen)
  - Reinigungsdauer
  - Nächste Anreise

#### Status
- **green**: Task aktiv (läuft)
- **grey**: Task erledigt
- **default**: Task offen

#### Timer & Progress
- **Start**: Task starten (Timer läuft)
- **Stop**: Timer stoppen und Ist-Zeit speichern
- **Erledigt**: Task als erledigt markieren
- **Rückgängig**: Erledigte Tasks wieder öffnen
- **Notiz**: AJAX-basiertes Notiz-Formular (Modal)

#### Live-Anzeige
- Live-Timer: "läuft seit X min — noch ca. Y min (von Z)"
- Progress-Bar: Fortschritt in Prozent
- Über-Stunden Warnung (rot) wenn Ist > Geplant

#### Monatsübersicht
- Verwendete Stunden im aktuellen Monat
- Warnung bei Überschreitung des Monatslimits

---

## 💰 Zeit- & Kostenverwaltung

### Staff-Profil
- **Maximal verfügbare Stunden** pro Monat
- **Stundenlohn** in Euro

### Zeit-Tracking
- Automatische Zeitmessung via Start/Stop
- Speicherung in `TimeLog`:
  - Startzeit
  - Endzeit
  - Tatsächliche Minuten
  - Staff-ID + Task-ID

### Export-Funktion
Excel-Export (`/admin/{token}/export?month=YYYY-MM`):
- Datum
- Apartment
- Staff
- Geplante Minuten
- Tatsächliche Minuten
- Stundensatz
- Kosten (€)
- Notizen

---

## 🔧 Konfiguration

### Environment Variables

```bash
# Admin-Zugriff
ADMIN_TOKEN=<geheimer-token>

# Smoobu API
SMOOBU_API_KEY=<api-key>
SMOOBU_BASE_URL=https://login.smoobu.com/api

# Sync-Interval (Minuten)
REFRESH_INTERVAL_MINUTES=60

# Zeitzone
TIMEZONE=Europe/Berlin

# Base URL für Magic Links
BASE_URL=https://your-app.onrender.com
```

### Installation

```bash
pip install -r requirements.txt
```

### Start

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## 📊 Datenfluss

```
Smoobu API
    ↓ (every 60 min)
refresh_bookings_job()
    ↓
Bookings Table
    ↓
upsert_tasks_from_bookings()
    ↓
Tasks Table
    ↓
Staff Assignment (Admin)
    ↓
Cleaner View
    ↓
Start/Stop Timer
    ↓
TimeLog
    ↓
Export (CSV/Excel)
```

---

## 🔐 Sicherheit

- Admin-Zugriff nur via Token (`/admin/{token}`)
- Cleaner-Zugriff nur via Magic Token (`/cleaner/{token}`)
- Token werden bei Staff-Anlage automatisch generiert (16 Bytes hex)
- Geschützte Routen: HTTPException(403) bei ungültigen Tokens

---

## 📝 Notizen

- Erledigte Tasks können rückgängig gemacht werden
- Gesperrte Tasks werden bei Auto-Sync nicht überschrieben
- Apartment-Konfiguration (planned_minutes) wird nur für neue Tasks verwendet
- Automatische Bereinigung: Tasks ohne Datum werden entfernt
- Live-Timer Update: alle 30 Sekunden

---

## 🚀 Deployment (Render)

1. Git Repository verbinden
2. Environment Variables setzen
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Health Check: `/health`

---

## 📦 Versionen

- **v6.3**: Live-Timer, Progressbar, AJAX-Notizen

