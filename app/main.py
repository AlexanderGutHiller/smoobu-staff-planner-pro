
import os, json, datetime as dt, csv, io, logging
from typing import List, Optional, Dict
from fastapi import FastAPI, Request, Depends, Form, HTTPException, Query
from fastapi.responses import RedirectResponse, StreamingResponse, PlainTextResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .db import init_db, SessionLocal
from .models import Booking, Staff, Apartment, Task, TimeLog
from .services_smoobu import SmoobuClient
from .utils import new_token, today_iso, now_iso
from .sync import upsert_tasks_from_bookings

def detect_language(request: Request) -> str:
    """Erkenne Browser-Sprache aus Cookie, Query-Parameter oder Accept-Language Header"""
    # Zuerst Cookie überprüfen
    lang_cookie = request.cookies.get("lang", "")
    if lang_cookie in ["de", "en", "fr", "it", "es", "ro", "ru", "bg"]:
        return lang_cookie
    
    # Dann Query-Parameter überprüfen
    lang_query = request.query_params.get("lang", "")
    if lang_query in ["de", "en", "fr", "it", "es", "ro", "ru", "bg"]:
        return lang_query
    
    # Dann Accept-Language Header
    accept_lang = request.headers.get("accept-language", "de").lower()
    if "en" in accept_lang:
        return "en"
    elif "fr" in accept_lang:
        return "fr"
    elif "it" in accept_lang:
        return "it"
    elif "es" in accept_lang:
        return "es"
    elif "ro" in accept_lang:
        return "ro"
    elif "ru" in accept_lang:
        return "ru"
    elif "bg" in accept_lang:
        return "bg"
    return "de"  # Default: Deutsch

def get_translations(lang: str) -> Dict[str, str]:
    """Übersetzungen für verschiedene Sprachen"""
    translations = {
               "de": {
                   "tasks": "Einsätze", "team": "Team", "apartments": "Apartments", "import_now": "Import jetzt",
                   "cleanup": "Bereinigen", "date": "Datum", "apartment": "Apartment", "planned": "Geplant",
                   "status": "Status", "actual": "Tatsächlich", "next_arrival": "Nächste Anreise",
                   "save": "Speichern", "today": "Heute", "week": "Diese Woche", "month": "Dieser Monat",
                   "next7": "Nächste 7 Tage", "all": "Alle", "erledigt": "Erledigt", "läuft": "Läuft", "offen": "Offen", "pausiert": "Pausiert",
                   "min": "min", "noch": "noch ca.", "über_zeit": "Über Zeit", "start": "Start", "pause": "Pause",
                   "fertig": "Fertig", "wieder_öffnen": "Wieder öffnen", "notiz": "Notiz", "meine_einsätze": "Meine Einsätze",
                   "monatslimit": "Achtung: Du hast dein Monatslimit von", "std_überschritten": "Std überschritten",
                   "aktuell": "Std erfasst.", "monat_erfasst": "Aktueller Monat:",
                   "keine_einsätze": "Keine Einsätze vorhanden", "nächste_anreise": "Nächste Anreise",
                   "erw": "Erw.", "kinder": "Kinder", "verbleibend": "verbleibend:",
                   "erledigte_ausblenden": "Erledigte ausblenden", "erledigte_anzeigen": "Erledigte anzeigen",
                   "erledigte_aufgaben": "Erledigte Aufgaben", "offene_aufgaben": "Offene Aufgaben",
                   "datum": "Datum", "ma": "MA", "lock": "Lock", "zurück": "Zurück",
                   "neue_aufgabe": "Neue Aufgabe", "tätigkeit": "Tätigkeit", "dauer": "Dauer (Min)", "beschreibung": "Beschreibung",
                   "erstellen": "Erstellen", "abbrechen": "Abbrechen",
                   "stunden": "Stunden", "vorletzter_monat": "Vorletzter Monat", "letzter_monat": "Letzter Monat", "aktueller_monat": "Aktueller Monat",
                   "geleistete_stunden": "Geleistete Stunden", "manuelle_aufgabe": "Manuelle Aufgabe",
                   "pending": "Ausstehend", "accepted": "Angenommen", "rejected": "Abgelehnt",
                   "annehmen": "Annehmen", "ablehnen": "Ablehnen", "zuweisung": "Zuweisung",
                   "checklist": "Checkliste", "kurtaxe_registriert": "Kurtaxe registriert",
                   "kurtaxe_bestaetigt": "Kurtaxe bestätigt", "checkin_vorbereitet": "Check-in vorbereitet",
                   "kurtaxe_bezahlt": "Kurtaxe bezahlt", "babybetten": "Babybetten"
               },
               "en": {
                   "tasks": "Tasks", "team": "Team", "apartments": "Apartments", "import_now": "Import now",
                   "cleanup": "Clean up", "date": "Date", "apartment": "Apartment", "planned": "Planned",
                   "status": "Status", "actual": "Actual", "next_arrival": "Next Arrival",
                   "save": "Save", "today": "Today", "week": "This Week", "month": "This Month",
                   "next7": "Next 7 Days", "all": "All", "erledigt": "Done", "läuft": "Running", "offen": "Open", "pausiert": "Paused",
                   "min": "min", "noch": "ca.", "über_zeit": "Over time", "start": "Start", "pause": "Pause",
                   "fertig": "Done", "wieder_öffnen": "Reopen", "notiz": "Note", "meine_einsätze": "My Tasks",
                   "monatslimit": "Warning: You have exceeded your monthly limit of", "std_überschritten": "hours",
                   "aktuell": "hours logged.", "monat_erfasst": "Current month:",
                   "keine_einsätze": "No tasks available", "nächste_anreise": "Next Arrival",
                   "erw": "Adults", "kinder": "Children", "verbleibend": "remaining:",
                   "erledigte_ausblenden": "Hide completed", "erledigte_anzeigen": "Show completed",
                   "erledigte_aufgaben": "Completed Tasks", "offene_aufgaben": "Open Tasks",
                   "datum": "Date", "ma": "Staff", "lock": "Lock", "zurück": "Back",
                   "neue_aufgabe": "New Task", "tätigkeit": "Activity", "dauer": "Duration (Min)", "beschreibung": "Description",
                   "erstellen": "Create", "abbrechen": "Cancel",
                   "stunden": "Hours", "vorletzter_monat": "2 Months Ago", "letzter_monat": "Last Month", "aktueller_monat": "Current Month",
                   "geleistete_stunden": "Hours Worked", "manuelle_aufgabe": "Manual Task",
                   "pending": "Pending", "accepted": "Accepted", "rejected": "Rejected",
                   "annehmen": "Accept", "ablehnen": "Reject", "zuweisung": "Assignment",
                   "checklist": "Checklist", "kurtaxe_registriert": "Tourist tax registered",
                   "kurtaxe_bestaetigt": "Tourist tax confirmed", "checkin_vorbereitet": "Check-in prepared",
                   "kurtaxe_bezahlt": "Tourist tax paid", "babybetten": "Baby cots"
               },
               "fr": {
                   "tasks": "Tâches", "team": "Équipe", "apartments": "Appartements", "import_now": "Importer maintenant",
                   "cleanup": "Nettoyer", "date": "Date", "apartment": "Appartement", "planned": "Prévu",
                   "status": "Statut", "actual": "Réel", "next_arrival": "Prochaine arrivée",
                   "save": "Sauvegarder", "today": "Aujourd'hui", "week": "Cette semaine", "month": "Ce mois",
                   "next7": "7 prochains jours", "all": "Tous", "erledigt": "Terminé", "läuft": "En cours", "offen": "Ouvert", "pausiert": "En pause",
                   "min": "min", "noch": "encore", "über_zeit": "Dépassé", "start": "Démarrer", "pause": "Pause",
                   "fertig": "Terminé", "wieder_öffnen": "Rouvrir", "notiz": "Note", "meine_einsätze": "Mes tâches",
                   "monatslimit": "Attention: Vous avez dépassé votre limite mensuelle de", "std_überschritten": "heures",
                   "aktuell": "heures enregistrées.", "monat_erfasst": "Mois actuel:",
                   "keine_einsätze": "Aucune tâche disponible", "nächste_anreise": "Prochaine arrivée",
                   "erw": "Adultes", "kinder": "Enfants", "verbleibend": "restant:",
                   "erledigte_ausblenden": "Masquer terminées", "erledigte_anzeigen": "Afficher terminées",
                   "erledigte_aufgaben": "Tâches terminées", "offene_aufgaben": "Tâches ouvertes",
                   "datum": "Date", "ma": "Équipe", "lock": "Verrouillé", "zurück": "Retour",
                   "neue_aufgabe": "Nouvelle tâche", "tätigkeit": "Activité", "dauer": "Durée (Min)", "beschreibung": "Description",
                   "erstellen": "Créer", "abbrechen": "Annuler",
                   "stunden": "Heures", "vorletzter_monat": "Il y a 2 mois", "letzter_monat": "Mois dernier", "aktueller_monat": "Mois actuel",
                   "geleistete_stunden": "Heures travaillées", "manuelle_aufgabe": "Tâche manuelle",
                   "pending": "En attente", "accepted": "Accepté", "rejected": "Refusé",
                   "annehmen": "Accepter", "ablehnen": "Refuser", "zuweisung": "Affectation",
                   "checklist": "Liste de contrôle", "kurtaxe_registriert": "Taxe de séjour enregistrée",
                   "kurtaxe_bestaetigt": "Taxe de séjour confirmée", "checkin_vorbereitet": "Check-in préparé",
                   "kurtaxe_bezahlt": "Taxe de séjour payée", "babybetten": "Lits bébé"
               },
               "it": {
                   "tasks": "Compiti", "team": "Squadra", "apartments": "Appartamenti", "import_now": "Importa ora",
                   "cleanup": "Pulisci", "date": "Data", "apartment": "Appartamento", "planned": "Pianificato",
                   "status": "Stato", "actual": "Effettivo", "next_arrival": "Prossimo arrivo",
                   "save": "Salva", "today": "Oggi", "week": "Questa settimana", "month": "Questo mese",
                   "next7": "Prossimi 7 giorni", "all": "Tutti", "erledigt": "Completato", "läuft": "In corso", "offen": "Aperto", "pausiert": "In pausa",
                   "min": "min", "noch": "ancora", "über_zeit": "Oltre il tempo", "start": "Avvia", "pause": "Pausa",
                   "fertig": "Completato", "wieder_öffnen": "Riapri", "notiz": "Nota", "meine_einsätze": "I miei compiti",
                   "monatslimit": "Attenzione: Hai superato il tuo limite mensile di", "std_überschritten": "ore",
                   "aktuell": "ore registrate.", "monat_erfasst": "Mese corrente:",
                   "keine_einsätze": "Nessun compito disponibile", "nächste_anreise": "Prossimo arrivo",
                   "erw": "Adulti", "kinder": "Bambini", "verbleibend": "rimanenti:",
                   "erledigte_ausblenden": "Nascondi completati", "erledigte_anzeigen": "Mostra completati",
                   "erledigte_aufgaben": "Compiti completati", "offene_aufgaben": "Compiti aperti",
                   "datum": "Data", "ma": "Squadra", "lock": "Bloccato", "zurück": "Indietro",
                   "neue_aufgabe": "Nuovo compito", "tätigkeit": "Attività", "dauer": "Durata (Min)", "beschreibung": "Descrizione",
                   "erstellen": "Crea", "abbrechen": "Annulla",
                   "stunden": "Ore", "vorletzter_monat": "2 mesi fa", "letzter_monat": "Mese scorso", "aktueller_monat": "Mese corrente",
                   "geleistete_stunden": "Ore lavorate", "manuelle_aufgabe": "Compito manuale",
                   "pending": "In attesa", "accepted": "Accettato", "rejected": "Rifiutato",
                   "annehmen": "Accetta", "ablehnen": "Rifiuta", "zuweisung": "Assegnazione",
                   "checklist": "Lista di controllo", "kurtaxe_registriert": "Tassa di soggiorno registrata",
                   "kurtaxe_bestaetigt": "Tassa di soggiorno confermata", "checkin_vorbereitet": "Check-in preparato",
                   "kurtaxe_bezahlt": "Tassa di soggiorno pagata", "babybetten": "Culle per bebè"
               },
               "es": {
                   "tasks": "Tareas", "team": "Equipo", "apartments": "Apartamentos", "import_now": "Importar ahora",
                   "cleanup": "Limpiar", "date": "Fecha", "apartment": "Apartamento", "planned": "Planificado",
                   "status": "Estado", "actual": "Real", "next_arrival": "Próxima llegada",
                   "save": "Guardar", "today": "Hoy", "week": "Esta semana", "month": "Este mes",
                   "next7": "Próximos 7 días", "all": "Todos", "erledigt": "Completado", "läuft": "En curso", "offen": "Abierto", "pausiert": "Pausado",
                   "min": "min", "noch": "aún", "über_zeit": "Sobre tiempo", "start": "Iniciar", "pause": "Pausa",
                   "fertig": "Completado", "wieder_öffnen": "Reabrir", "notiz": "Nota", "meine_einsätze": "Mis tareas",
                   "monatslimit": "Atención: Has excedido tu límite mensual de", "std_überschritten": "horas",
                   "aktuell": "horas registradas.", "monat_erfasst": "Mes actual:",
                   "keine_einsätze": "No hay tareas disponibles", "nächste_anreise": "Próxima llegada",
                   "erw": "Adultos", "kinder": "Niños", "verbleibend": "restantes:",
                   "erledigte_ausblenden": "Ocultar completadas", "erledigte_anzeigen": "Mostrar completadas",
                   "erledigte_aufgaben": "Tareas completadas", "offene_aufgaben": "Tareas abiertas",
                   "datum": "Fecha", "ma": "Equipo", "lock": "Bloqueado", "zurück": "Atrás",
                   "neue_aufgabe": "Nueva tarea", "tätigkeit": "Actividad", "dauer": "Duración (Min)", "beschreibung": "Descripción",
                   "erstellen": "Crear", "abbrechen": "Cancelar",
                   "stunden": "Horas", "vorletzter_monat": "Hace 2 meses", "letzter_monat": "Mes pasado", "aktueller_monat": "Mes actual",
                   "geleistete_stunden": "Horas trabajadas", "manuelle_aufgabe": "Tarea manual",
                   "pending": "Pendiente", "accepted": "Aceptado", "rejected": "Rechazado",
                   "annehmen": "Aceptar", "ablehnen": "Rechazar", "zuweisung": "Asignación",
                   "checklist": "Lista de verificación", "kurtaxe_registriert": "Tasa turística registrada",
                   "kurtaxe_bestaetigt": "Tasa turística confirmada", "checkin_vorbereitet": "Check-in preparado",
                   "kurtaxe_bezahlt": "Tasa turística pagada", "babybetten": "Cunas para bebé"
               },
               "ro": {
                   "tasks": "Sarcini", "team": "Echipa", "apartments": "Apartamente", "import_now": "Importă acum",
                   "cleanup": "Curățare", "date": "Dată", "apartment": "Apartament", "planned": "Planificat",
                   "status": "Status", "actual": "Real", "next_arrival": "Următoarea sosire",
                   "save": "Salvează", "today": "Azi", "week": "Săptămâna aceasta", "month": "Luna aceasta",
                   "next7": "Următoarele 7 zile", "all": "Toate", "erledigt": "Finalizat", "läuft": "În curs", "offen": "Deschis", "pausiert": "Întrerupt",
                   "min": "min", "noch": "ca.", "über_zeit": "Peste timp", "start": "Start", "pause": "Pauză",
                   "fertig": "Finalizat", "wieder_öffnen": "Redeschide", "notiz": "Notă", "meine_einsätze": "Sarcinile mele",
                   "monatslimit": "Atenție: Ai depășit limita lunară de", "std_überschritten": "ore",
                   "aktuell": "ore înregistrate.", "monat_erfasst": "Luna curentă:",
                   "keine_einsätze": "Nu există sarcini", "nächste_anreise": "Următoarea sosire",
                   "erw": "Adulți", "kinder": "Copii", "verbleibend": "rămâne:",
                   "erledigte_ausblenden": "Ascunde finalizate", "erledigte_anzeigen": "Afișează finalizate",
                   "erledigte_aufgaben": "Sarcini finalizate", "offene_aufgaben": "Sarcini deschise",
                   "datum": "Dată", "ma": "Echipa", "lock": "Blocare", "zurück": "Înapoi",
                   "neue_aufgabe": "Sarcină nouă", "tätigkeit": "Activitate", "dauer": "Durată (Min)", "beschreibung": "Descriere",
                   "erstellen": "Creează", "abbrechen": "Anulează",
                   "stunden": "Ore", "vorletzter_monat": "Acum 2 luni", "letzter_monat": "Luna trecută", "aktueller_monat": "Luna curentă",
                   "geleistete_stunden": "Ore lucrate", "manuelle_aufgabe": "Sarcină manuală",
                   "pending": "În așteptare", "accepted": "Acceptat", "rejected": "Refuzat",
                   "annehmen": "Acceptă", "ablehnen": "Refuză", "zuweisung": "Atribuire",
                   "checklist": "Listă de verificare", "kurtaxe_registriert": "Taxa de turism înregistrată",
                   "kurtaxe_bestaetigt": "Taxa de turism confirmată", "checkin_vorbereitet": "Check-in pregătit",
                   "kurtaxe_bezahlt": "Taxa de turism plătită", "babybetten": "Pătuțuri pentru bebeluși"
               },
               "ru": {
                   "tasks": "Задачи", "team": "Команда", "apartments": "Апартаменты", "import_now": "Импорт сейчас",
                   "cleanup": "Очистка", "date": "Дата", "apartment": "Апартамент", "planned": "Запланировано",
                   "status": "Статус", "actual": "Фактически", "next_arrival": "Следующий приезд",
                   "save": "Сохранить", "today": "Сегодня", "week": "На этой неделе", "month": "В этом месяце",
                   "next7": "Следующие 7 дней", "all": "Все", "erledigt": "Выполнено", "läuft": "Выполняется", "offen": "Открыто", "pausiert": "Приостановлено",
                   "min": "мин", "noch": "около", "über_zeit": "Превышено", "start": "Старт", "pause": "Пауза",
                   "fertig": "Готово", "wieder_öffnen": "Открыть снова", "notiz": "Заметка", "meine_einsätze": "Мои задачи",
                   "monatslimit": "Внимание: Вы превысили месячный лимит", "std_überschritten": "часов",
                   "aktuell": "часов записано.", "monat_erfasst": "Текущий месяц:",
                   "keine_einsätze": "Нет задач", "nächste_anreise": "Следующий приезд",
                   "erw": "Взрослые", "kinder": "Дети", "verbleibend": "осталось:",
                   "erledigte_ausblenden": "Скрыть выполненные", "erledigte_anzeigen": "Показать выполненные",
                   "erledigte_aufgaben": "Выполненные задачи", "offene_aufgaben": "Открытые задачи",
                   "datum": "Дата", "ma": "Команда", "lock": "Заблокировано", "zurück": "Назад",
                   "neue_aufgabe": "Новая задача", "tätigkeit": "Деятельность", "dauer": "Длительность (Мин)", "beschreibung": "Описание",
                   "erstellen": "Создать", "abbrechen": "Отмена",
                   "stunden": "Часы", "vorletzter_monat": "2 месяца назад", "letzter_monat": "Прошлый месяц", "aktueller_monat": "Текущий месяц",
                   "geleistete_stunden": "Отработанные часы", "manuelle_aufgabe": "Ручная задача",
                   "pending": "Ожидание", "accepted": "Принято", "rejected": "Отклонено",
                   "annehmen": "Принять", "ablehnen": "Отклонить", "zuweisung": "Назначение",
                   "checklist": "Чек-лист", "kurtaxe_registriert": "Туристический налог зарегистрирован",
                   "kurtaxe_bestaetigt": "Туристический налог подтверждён", "checkin_vorbereitet": "Заселение подготовлено",
                   "kurtaxe_bezahlt": "Туристический налог оплачен", "babybetten": "Детские кроватки"
               },
               "bg": {
                   "tasks": "Задачи", "team": "Екип", "apartments": "Апартаменти", "import_now": "Импортирай сега",
                   "cleanup": "Почистване", "date": "Дата", "apartment": "Апартамент", "planned": "Планирано",
                   "status": "Статус", "actual": "Действително", "next_arrival": "Следващо пристигане",
                   "save": "Запази", "today": "Днес", "week": "Тази седмица", "month": "Този месец",
                   "next7": "Следващите 7 дни", "all": "Всички", "erledigt": "Завършено", "läuft": "В ход", "offen": "Отворено", "pausiert": "Паузирано",
                   "min": "мин", "noch": "остават", "über_zeit": "Над времето", "start": "Старт", "pause": "Пауза",
                   "fertig": "Готово", "wieder_öffnen": "Отвори отново", "notiz": "Бележка", "meine_einsätze": "Моите задачи",
                   "monatslimit": "Внимание: Надхвърлихте месечния си лимит от", "std_überschritten": "часа",
                   "aktuell": "часа записани.", "monat_erfasst": "Текущ месец:",
                   "keine_einsätze": "Няма задачи", "nächste_anreise": "Следващо пристигане",
                   "erw": "Възрастни", "kinder": "Деца", "verbleibend": "остават:",
                   "erledigte_ausblenden": "Скрий завършени", "erledigte_anzeigen": "Покажи завършени",
                   "erledigte_aufgaben": "Завършени задачи", "offene_aufgaben": "Отворени задачи",
                   "datum": "Дата", "ma": "Екип", "lock": "Заключено", "zurück": "Назад",
                   "neue_aufgabe": "Нова задача", "tätigkeit": "Дейност", "dauer": "Продължителност (Мин)", "beschreibung": "Описание",
                   "erstellen": "Създай", "abbrechen": "Отказ",
                   "stunden": "Часове", "vorletzter_monat": "Преди 2 месеца", "letzter_monat": "Миналия месец", "aktueller_monat": "Текущ месец",
                   "geleistete_stunden": "Отработени часове", "manuelle_aufgabe": "Ръчна задача",
                   "pending": "В очакване", "accepted": "Прието", "rejected": "Отхвърлено",
                   "annehmen": "Приеми", "ablehnen": "Отхвърли", "zuweisung": "Назначаване",
                   "checklist": "Контролен списък", "kurtaxe_registriert": "Курортна такса регистрирана",
                   "kurtaxe_bestaetigt": "Курортна такса потвърдена", "checkin_vorbereitet": "Чек-ин подготвен",
                   "kurtaxe_bezahlt": "Курортна такса платена", "babybetten": "Бебешки легла"
               }
    }
    return translations.get(lang, translations["de"])

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Berlin")
REFRESH_INTERVAL_MINUTES = int(os.getenv("REFRESH_INTERVAL_MINUTES", "60"))
BASE_URL = os.getenv("BASE_URL", "")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")
# WhatsApp/Twilio Configuration
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "")  # Format: whatsapp:+14155238886
APP_VERSION = os.getenv("APP_VERSION", "v6.3")
APP_BUILD_DATE = os.getenv("APP_BUILD_DATE", dt.date.today().strftime("%Y-%m-%d"))

log = logging.getLogger("smoobu")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Smoobu Staff Planner Pro (v6.3)")

if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="app/templates")
templates.env.globals.update({
    "APP_VERSION": APP_VERSION,
    "APP_BUILD_DATE": APP_BUILD_DATE,
    "APP_VERSION_DISPLAY": f"Version {APP_VERSION} · {APP_BUILD_DATE}",
    "dt": dt,
})

def _parse_iso_date(s: str):
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def date_de(s: str) -> str:
    d = _parse_iso_date(s)
    return d.strftime("%d.%m.%Y") if d else (s or "")

def date_wd_de(s: str, style: str = "short") -> str:
    d = _parse_iso_date(s)
    if not d:
        return s or ""
    wd_short = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    wd_long  = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
    name = wd_long[d.weekday()] if style == "long" else wd_short[d.weekday()]
    return f"{name}, {d.strftime('%d.%m.%Y')}"

def minutes_to_hhmm(minutes: Optional[int]) -> str:
    """Konvertiere Minuten in hh:mm Format"""
    if minutes is None:
        return "--:--"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"

templates.env.filters["date_de"] = date_de
templates.env.filters["date_wd_de"] = date_wd_de
templates.env.filters["minutes_to_hhmm"] = minutes_to_hhmm

def _send_email(to_email: str, subject: str, body_text: str, body_html: str | None = None):
    if not (SMTP_HOST and SMTP_FROM):
        log.warning("SMTP not configured, skipping email to %s", to_email)
        return
    import smtplib
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
            s.starttls()
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
        log.info("📧 Sent email to %s", to_email)
    except Exception as e:
        log.error("Email send failed to %s: %s", to_email, e)

def _send_whatsapp(to_phone: str, message: str):
    """Sende WhatsApp-Nachricht über Twilio"""
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM):
        log.warning("Twilio not configured, skipping WhatsApp to %s", to_phone)
        return False
    
    if not to_phone or not to_phone.strip():
        log.warning("No phone number provided for WhatsApp")
        return False
    
    try:
        from twilio.rest import Client
        
        # Normalisiere Telefonnummer (entferne Leerzeichen, füge + hinzu falls nötig)
        phone = to_phone.strip().replace(" ", "").replace("-", "")
        if not phone.startswith("+"):
            # Wenn keine Ländervorwahl, füge +49 für Deutschland hinzu (oder konfigurierbar)
            if phone.startswith("0"):
                phone = "+49" + phone[1:]  # 0171... -> +49171...
            else:
                phone = "+49" + phone  # 171... -> +49171...
        whatsapp_to = f"whatsapp:{phone}"
        
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        log.info("📱 Sending WhatsApp: from=%s, to=%s, message_length=%d", 
                 TWILIO_WHATSAPP_FROM, whatsapp_to, len(message))
        message_obj = client.messages.create(
            body=message,
            from_=TWILIO_WHATSAPP_FROM,
            to=whatsapp_to
        )
        status = getattr(message_obj, 'status', 'unknown')
        error_code = getattr(message_obj, 'error_code', None)
        error_message = getattr(message_obj, 'error_message', None)
        
        log.info("📱 WhatsApp API Response: SID=%s, Status=%s, ErrorCode=%s, ErrorMessage=%s", 
                message_obj.sid, status, error_code, error_message)
        
        if status in ['queued', 'sent', 'delivered']:
            log.info("✅ WhatsApp sent successfully to %s (Status: %s)", phone, status)
            return True
        elif status == 'failed':
            log.error("❌ WhatsApp failed to %s: %s (Code: %s)", phone, error_message, error_code)
            return False
        else:
            log.warning("⚠️ WhatsApp status unclear for %s: %s", phone, status)
            return True  # Return True anyway, as message was accepted by Twilio
    except ImportError:
        log.error("Twilio library not installed. Install with: pip install twilio")
        return False
    except Exception as e:
        log.error("WhatsApp send failed to %s: %s", to_phone, e, exc_info=True)
        return False

def build_assignment_whatsapp_message(lang: str, staff_name: str, items: list, base_url: str) -> str:
    """Erstelle WhatsApp-Nachricht für Zuweisungen"""
    trans = get_translations(lang)
    msg = f"*{trans.get('zuweisung', 'Zuweisung')} · {staff_name}*\n\n"
    for i, it in enumerate(items, 1):
        msg += f"*{i}. {it['apt']}* - {it['date']}\n"
        if it['guest']:
            msg += f"👤 {it['guest']}\n"
        msg += f"📝 {it['desc']}\n"
        msg += f"✅ {it['accept']}\n"
        msg += f"❌ {it['reject']}\n\n"
    return msg

def build_assignment_email(lang: str, staff_name: str, items: list, base_url: str) -> tuple[str, str, str]:
    trans = get_translations(lang)
    subject = f"{trans.get('zuweisung','Zuweisung')}: {len(items)} {trans.get('tasks','Tasks')}"
    # Text-Version
    tlines = [f"{trans.get('team','Team')}: {staff_name}", ""]
    for it in items:
        tlines.append(f"- {it['date']}: {it['desc']} ({it['apt']})")
        if it.get('guest'):
            tlines.append(f"  {it['guest']}")
        tlines.append(f"  {trans.get('annehmen','Annehmen')}: {it['accept']}")
        tlines.append(f"  {trans.get('ablehnen','Ablehnen')}: {it['reject']}")
        tlines.append("")
    body_text = "\n".join(tlines).strip()
    # HTML-Version (Inline-Styles für breite Kompatibilität)
    cards = []
    for it in items:
        guest_html = f"<div style='color:#6c757d;font-size:13px;margin-top:4px;'>{it['guest']}</div>" if it.get('guest') else ""
        cards.append(f"""
        <div style='border:1px solid #dee2e6;border-radius:8px;padding:12px;margin:10px 0;background:#ffffff;'>
          <div style='display:flex;justify-content:space-between;align-items:center;'>
            <div style='font-weight:700;font-size:16px'>{it['date']} · {it['apt']}</div>
            <span style='background:#0d6efd;color:#fff;border-radius:12px;padding:4px 8px;font-size:12px;'>{trans.get('zuweisung','Zuweisung')}</span>
          </div>
          <div style='margin-top:6px;font-size:14px;'>{it['desc']}</div>
          {guest_html}
          <div style='display:flex;gap:8px;margin-top:12px;'>
            <a href='{it['accept']}' style='text-decoration:none;background:#198754;color:#fff;padding:8px 10px;border-radius:6px;font-weight:600;'>{trans.get('annehmen','Annehmen')}</a>
            <a href='{it['reject']}' style='text-decoration:none;background:#dc3545;color:#fff;padding:8px 10px;border-radius:6px;font-weight:600;'>{trans.get('ablehnen','Ablehnen')}</a>
          </div>
        </div>
        """)
    body_html = f"""
    <div style='font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#f8f9fa;padding:16px;'>
      <div style='max-width:680px;margin:0 auto;'>
        <h2 style='margin:0 0 12px 0;font-size:20px;'>{trans.get('zuweisung','Zuweisung')} · {staff_name}</h2>
        {''.join(cards)}
        <div style='color:#6c757d;font-size:12px;margin-top:12px;'>
          {trans.get('hinweis','Hinweis') if 'hinweis' in trans else 'Hinweis'}: Diese E-Mail fasst Aufgaben der letzten 30 Minuten zusammen.
        </div>
      </div>
    </div>
    """
    return subject, body_text, body_html

def send_assignment_emails_job():
    base_url = BASE_URL.rstrip("/") or ""
    with SessionLocal() as db:
        pending = db.query(Task).filter(Task.assignment_status=="pending", Task.assigned_staff_id!=None, Task.assign_notified_at==None).all()
        if not pending:
            return []
        staff_ids = {t.assigned_staff_id for t in pending if t.assigned_staff_id}
        report = []
        for sid in staff_ids:
            staff = db.get(Staff, sid)
            if not staff or not (staff.email or "").strip():
                continue
            lang = (staff.language or "de")
            token = staff.magic_token
            tasks_for_staff = [t for t in pending if t.assigned_staff_id==sid]
            items = []
            trans = get_translations(lang)
            for t in tasks_for_staff:
                apt_name = ""
                if t.apartment_id:
                    apt = db.get(Apartment, t.apartment_id)
                    apt_name = apt.name if apt else ""
                guest_str = ""
                if t.booking_id:
                    b = db.get(Booking, t.booking_id)
                    if b:
                        gname = (b.guest_name or "").strip()
                        if gname:
                            guest_str = f"{gname}"
                        else:
                            # Adults/children fallback
                            ac = []
                            if b.adults:
                                ac.append(f"{trans.get('erw','Erw.')} {b.adults}")
                            if b.children:
                                ac.append(f"{trans.get('kinder','Kinder')} {b.children}")
                            guest_str = ", ".join(ac)
                desc = (t.notes or "").strip() or get_translations(lang).get('tätigkeit','Tätigkeit')
                accept_link = f"{base_url}/c/{token}/accept?task_id={t.id}"
                reject_link = f"{base_url}/c/{token}/reject?task_id={t.id}"
                items.append({
                    'date': t.date,
                    'apt': apt_name,
                    'desc': desc,
                    'guest': guest_str,
                    'accept': accept_link,
                    'reject': reject_link,
                })
            subject, body_text, body_html = build_assignment_email(lang, staff.name, items, base_url)
            _send_email(staff.email, subject, body_text, body_html)
            
            # WhatsApp-Benachrichtigung senden (falls Telefonnummer vorhanden)
            try:
                phone = getattr(staff, 'phone', None) or ""
                if phone and phone.strip():
                    log.info("📱 Attempting WhatsApp to %s for staff %s", phone, staff.name)
                    whatsapp_msg = build_assignment_whatsapp_message(lang, staff.name, items, base_url)
                    result = _send_whatsapp(phone, whatsapp_msg)
                    if result:
                        log.info("✅ WhatsApp sent successfully to %s", phone)
                    else:
                        log.warning("❌ WhatsApp send failed to %s (check logs above)", phone)
                else:
                    log.debug("No phone number for staff %s, skipping WhatsApp", staff.name)
            except Exception as e:
                log.error("WhatsApp notification error for staff %s: %s", staff.name, e, exc_info=True)
            
            now = now_iso()
            for t in tasks_for_staff:
                t.assign_notified_at = now
            try:
                phone = getattr(staff, 'phone', None) or ""
            except:
                phone = ""
            report.append({
                'staff_name': staff.name,
                'email': staff.email,
                'phone': phone,
                'count': len(items),
                'items': items,
            })
        db.commit()
        return report

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.on_event("startup")
async def startup_event():
    init_db()
    if not ADMIN_TOKEN:
        log.warning("ADMIN_TOKEN not set! Admin UI will be inaccessible.")
    try:
        await refresh_bookings_job()
    except Exception as e:
        log.exception("Initial import failed: %s", e)
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(refresh_bookings_job, IntervalTrigger(minutes=REFRESH_INTERVAL_MINUTES))
    # Bündel-E-Mails für Zuweisungen alle 30 Minuten
    scheduler.add_job(send_assignment_emails_job, IntervalTrigger(minutes=30))
    scheduler.start()

def _daterange(days=60):
    start = dt.date.today()
    end = start + dt.timedelta(days=days)
    return start.isoformat(), end.isoformat()

def _best_guest_name(it: dict) -> str:
    guest = it.get("guest") or {}
    # Häufige Felder
    candidates = [
        guest.get("fullName"),
        (f"{guest.get('firstName','')} {guest.get('lastName','')}".strip() or None),
        (f"{it.get('firstName','')} {it.get('lastName','')}".strip() or None),
        it.get("guestName"),
        it.get("mainGuestName"),
        it.get("contactName"),
        it.get("name"),
        (it.get("contact") or {}).get("name"),
    ]
    for c in candidates:
        if c and isinstance(c, str) and c.strip():
            return c.strip()
    return ""

def _guest_count_label(it: dict) -> str:
    try:
        adults = it.get("adults")
        children = it.get("children")
        # Alternativ-Felder absichern
        if adults is None:
            adults = it.get("numAdults") or it.get("guests") or 0
        if children is None:
            children = it.get("numChildren") or 0
        adults = int(adults or 0)
        children = int(children or 0)
        total = adults + children
        if total <= 0 and (adults > 0 or children > 0):
            total = adults + children
        if total > 0:
            # Einfache deutsche Bezeichnung
            return f"{total} Gäste"
    except Exception:
        pass
    return ""

async def refresh_bookings_job():
    client = SmoobuClient()
    start, end = _daterange(60)
    log.info("🔄 Starting refresh: %s to %s", start, end)
    items = client.get_reservations(start, end)
    log.info("📥 Fetched %d bookings from Smoobu", len(items))
    with SessionLocal() as db:
        seen_booking_ids: List[int] = []
        seen_apartment_ids: List[int] = []
        for it in items:
            b_id = int(it.get("id"))
            apt = it.get("apartment") or {}
            apt_id = int(apt.get("id")) if apt.get("id") is not None else None
            apt_name = apt.get("name") or ""
            guest_name = _best_guest_name(it)
            if guest_name:
                log.debug("📝 Guest name for booking %d: '%s'", b_id, guest_name)
            else:
                # Breiteres Logging zur Diagnose, wenn kein Name geliefert wird
                try:
                    log.warning("⚠️ No guest name in booking %d. Available keys: %s", b_id, list(it.keys()))
                    if it.get("guest"):
                        log.warning("⚠️ guest keys: %s", list((it.get("guest") or {}).keys()))
                    if it.get("contact"):
                        log.warning("⚠️ contact keys: %s", list((it.get("contact") or {}).keys()))
                    log.warning("⚠️ adults=%s children=%s guests=%s", it.get("adults"), it.get("children"), it.get("guests"))
                except Exception:
                    pass
                # Fallback: Gästeanzahl
                guest_name = _guest_count_label(it) or ""
            arrival = (it.get("arrival") or "")[:10]
            departure = (it.get("departure") or "")[:10]

            # Check if booking is cancelled or blocked
            is_blocked = it.get("isBlockedBooking", False) or it.get("blocked", False)
            status = it.get("status", "").lower() if it.get("status") else ""
            cancelled = status == "cancelled" or it.get("cancelled", False)
            is_internal = it.get("isInternal", False)
            
            # Check for various status
            is_draft = status == "draft"
            is_pending = status == "pending"
            is_on_hold = status == "on hold" or status == "on_hold"
            
            log.debug("Smoobu booking %d: apt='%s', arrival='%s', departure='%s', status='%s'", 
                     b_id, apt_name, arrival, departure, it.get("status"))
            
            # Log ALL fields for Romantik to debug
            if apt_name and "romantik" in apt_name.lower() and "2025-10-29" in departure:
                log.warning("🎯 ROMANTIK FULL BOOKING DATA: %s", it)
                log.warning("🎯 Status fields: type='%s', status='%s', cancelled=%s, blocked=%s, internal=%s, draft=%s, pending=%s, on_hold=%s", 
                           it.get("type"), status, cancelled, is_blocked, is_internal, is_draft, is_pending, is_on_hold)

            # Check booking type FIRST - before we update or create the booking
            booking_type = it.get("type", "").lower()
            
            # Check for cancelled, blocked, internal, draft, pending, on-hold bookings OR cancellation type - SKIP and DELETE these!
            should_skip = False
            reason = ""
            
            if booking_type == "cancellation":
                should_skip = True
                reason = "cancellation type"
            elif cancelled:
                should_skip = True
                reason = "cancelled"
            elif is_blocked:
                should_skip = True
                reason = "blocked"
            elif is_internal:
                should_skip = True
                reason = "internal"
            elif is_draft:
                should_skip = True
                reason = "draft"
            elif is_pending:
                should_skip = True
                reason = "pending"
            elif is_on_hold:
                should_skip = True
                reason = "on-hold"
            
            # Check for invalid bookings - also skip and delete
            if not departure or not departure.strip():
                log.info("⛔ SKIP INVALID booking %d (%s) - NO DEPARTURE, arrival='%s'", b_id, apt_name, arrival)
                should_skip = True
                reason = "invalid (no departure)"
            elif not arrival or not arrival.strip():
                log.info("⛔ SKIP INVALID booking %d (%s) - NO ARRIVAL, departure='%s'", b_id, apt_name, departure)
                should_skip = True
                reason = "invalid (no arrival)"
            elif departure <= arrival:
                log.info("⛔ SKIP INVALID booking %d (%s) - departure <= arrival ('%s' <= '%s')", b_id, apt_name, departure, arrival)
                should_skip = True
                reason = "invalid (departure <= arrival)"
            
            if should_skip:
                log.info("⛔ SKIP %s booking %d (%s) - arrival: %s, departure: %s", reason, b_id, apt_name, arrival, departure)
                # Sofort-Benachrichtigung an zugewiesene Cleaner über Storno + zugehörige Tasks löschen
                try:
                    # Sammle betroffene Tasks
                    tasks = db.query(Task).filter(Task.booking_id==b_id).all()
                    by_staff: Dict[int, list] = {}
                    for t in tasks:
                        if t.assigned_staff_id and t.assignment_status != "rejected":
                            by_staff.setdefault(t.assigned_staff_id, []).append(t)
                    for sid, tlist in by_staff.items():
                        staff = db.get(Staff, sid)
                        if not staff or not (staff.email or "").strip():
                            continue
                        lang = staff.language or "de"
                        trans = get_translations(lang)
                        # E-Mail-Inhalte pro Staff
                        items = []
                        for t in tlist:
                            token = staff.magic_token
                            items.append({
                                'date': t.date,
                                'apt': apt_name or "",
                                'desc': (t.notes or "").strip() or trans.get('tätigkeit','Tätigkeit'),
                                'link': f"{BASE_URL.rstrip('/')}/cleaner/{token}",
                            })
                        subject = f"{trans.get('cleanup','Bereinigen')}: {trans.get('zuweisung','Zuweisung')} storniert"
                        # Text
                        lines = [f"{trans.get('zuweisung','Zuweisung')} storniert:"]
                        for it in items:
                            lines.append(f"- {it['date']} · {it['apt']} · {it['desc']}")
                        lines.append("")
                        lines.append(items[0]['link'])
                        body_text = "\n".join(lines)
                        # HTML
                        cards = []
                        for it in items:
                            cards.append(f"""
                            <div style='border:1px solid #f1b0b7;border-radius:8px;padding:12px;margin:10px 0;background:#fff5f5;'>
                              <div style='display:flex;justify-content:space-between;align-items:center;'>
                                <div style='font-weight:700;font-size:16px'>{it['date']} · {it['apt']}</div>
                                <span style='background:#dc3545;color:#fff;border-radius:12px;padding:4px 8px;font-size:12px;'>Storniert</span>
                              </div>
                              <div style='margin-top:6px;font-size:14px;'>{it['desc']}</div>
                            </div>
                            """)
                        body_html = f"""
                        <div style='font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#f8f9fa;padding:16px;'>
                          <div style='max-width:680px;margin:0 auto;'>
                            <h2 style='margin:0 0 12px 0;font-size:20px;'>Storno: Aufgaben entfallen</h2>
                            {''.join(cards)}
                            <div style='margin-top:12px;'>
                              <a href='{items[0]['link']}' style='text-decoration:none;background:#0d6efd;color:#fff;padding:8px 10px;border-radius:6px;font-weight:600;'>Zur Übersicht</a>
                            </div>
                          </div>
                        </div>
                        """
                        _send_email(staff.email, subject, body_text, body_html)
                except Exception as e:
                    log.error("Error sending cancellation notifications for booking %d: %s", b_id, e)
                # Delete existing booking if it exists
                b_existing = db.get(Booking, b_id)
                if b_existing:
                    db.delete(b_existing)
                    log.info("🗑️ Deleted existing booking %d from database", b_id)
                # Lösche zugehörige Tasks direkt
                for t in db.query(Task).filter(Task.booking_id==b_id).all():
                    db.delete(t)
                db.commit()
                continue
            
            # Only log valid bookings
            log.info("✓ Valid booking %d (%s) - arrival: %s, departure: %s", b_id, apt_name, arrival, departure)
            
            if apt_id is not None and apt_id not in seen_apartment_ids:
                a = db.get(Apartment, apt_id)
                if not a:
                    a = Apartment(id=apt_id, name=apt_name, planned_minutes=90, active=True)
                    db.add(a)
                else:
                    a.name = apt_name or a.name
                seen_apartment_ids.append(apt_id)

            b = db.get(Booking, b_id)
            if not b:
                b = Booking(id=b_id)
                db.add(b)
            b.apartment_id = apt_id
            b.apartment_name = apt_name or ""
            b.arrival = (it.get("arrival") or "")[:10]
            b.departure = (it.get("departure") or "")[:10]
            b.nights = int(it.get("nights") or 0)
            b.adults = int(it.get("adults") or 1)
            b.children = int(it.get("children") or 0)
            b.guest_comments = (it.get("guestComments") or it.get("comments") or "")[:2000]
            b.guest_name = (guest_name or "").strip()
            if b.guest_name:
                log.debug("✅ Saving guest name '%s' for booking %d", b.guest_name, b_id)
            else:
                log.warning("⚠️ No guest name found for booking %d (apt: %s)", b_id, apt_name)
            
            seen_booking_ids.append(b_id)

        existing_ids = [row[0] for row in db.query(Booking.id).all()]
        for bid in existing_ids:
            if bid not in seen_booking_ids:
                db.delete(db.get(Booking, bid))

        db.commit()

        bookings = db.query(Booking).all()
        log.info("📋 Processing %d bookings from database", len(bookings))
        upsert_tasks_from_bookings(bookings)

        removed = 0
        for t in db.query(Task).all():
            if not t.date or not t.date.strip():
                db.delete(t); removed += 1
        if removed:
            log.info("🧹 Cleanup: %d Tasks ohne Datum entfernt.", removed)
        db.commit()
        log.info("✅ Refresh completed successfully")

@app.get("/", response_class=HTMLResponse)
async def root():
    return "<html><head><link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' rel='stylesheet'></head><body class='p-4' style='font-family:system-ui;'><h1>Smoobu Staff Planner Pro</h1><p>Service läuft. Admin-UI: <code>/admin/&lt;ADMIN_TOKEN&gt;</code></p><p>Health: <a href='/health'>/health</a></p></body></html>"

@app.get("/health")
async def health():
    return {"ok": True, "time": now_iso()}

@app.get("/set-language")
async def set_language(lang: str, redirect: str = "/"):
    """Setze die Sprache als Cookie und leite weiter"""
    if lang not in ["de", "en", "fr", "it", "es", "ro", "ru", "bg"]:
        lang = "de"
    
    # Erstelle Response mit Redirect
    response = RedirectResponse(url=redirect)
    response.set_cookie(
        key="lang",
        value=lang,
        max_age=365*24*60*60,  # 1 Jahr
        httponly=False,
        secure=False,
        samesite="lax"
    )
    return response

# -------------------- Admin UI --------------------
@app.get("/admin/{token}")
async def admin_home(request: Request, token: str, date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None), staff_id: Optional[int] = Query(None), apartment_id: Optional[int] = Query(None), show_done: int = 1, show_open: int = 1, db=Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403)
    
    lang = detect_language(request)
    trans = get_translations(lang)
    
    q = db.query(Task)
    if date_from: q = q.filter(Task.date >= date_from)
    if date_to: q = q.filter(Task.date <= date_to)
    if staff_id: q = q.filter(Task.assigned_staff_id == staff_id)
    if apartment_id: q = q.filter(Task.apartment_id == apartment_id)
    # Filter nach Status: erledigte und/oder offene Aufgaben
    from sqlalchemy import or_
    status_filters = []
    if show_done:
        status_filters.append(Task.status == "done")
    if show_open:
        status_filters.append(Task.status != "done")
    if status_filters:
        q = q.filter(or_(*status_filters))
    else:
        # Wenn beide Filter deaktiviert sind, zeige nichts
        q = q.filter(Task.id == -1)  # Unmögliche Bedingung
    tasks = q.order_by(Task.date, Task.id).all()
    staff = db.query(Staff).filter(Staff.active==True).all()
    apts = db.query(Apartment).filter(Apartment.active==True).all()
    apt_map = {a.id: a.name for a in apts}
    bookings = db.query(Booking).all()
    book_map = {b.id: (b.guest_name or "").strip() for b in bookings if b.guest_name}
    booking_details_map = {b.id: {'adults': b.adults or 0, 'children': b.children or 0, 'guest_name': (b.guest_name or "").strip()} for b in bookings}
    log.debug("📊 Created book_map with %d entries, %d have guest names", len(bookings), len([b for b in bookings if b.guest_name and b.guest_name.strip()]))
    
    # Timelog-Daten und Zusatzinformationen für jedes Task
    timelog_map = {}
    extras_map: Dict[int, Dict[str, bool]] = {}
    for t in tasks:
        # Summiere alle TimeLogs für diesen Task (nicht nur den letzten)
        all_tls = db.query(TimeLog).filter(TimeLog.task_id==t.id).all()
        total_minutes = 0
        latest_tl = None
        for tl in all_tls:
            if tl.actual_minutes:
                total_minutes += tl.actual_minutes
            # Finde den neuesten TimeLog für started_at/ended_at
            if not latest_tl or (tl.id and latest_tl.id and tl.id > latest_tl.id):
                latest_tl = tl
        
        if latest_tl or total_minutes > 0:
            timelog_map[t.id] = {
                'actual_minutes': total_minutes if total_minutes > 0 else (latest_tl.actual_minutes if latest_tl and latest_tl.actual_minutes else None),
                'started_at': latest_tl.started_at if latest_tl else None,
                'ended_at': latest_tl.ended_at if latest_tl else None
            }
        try:
            extras_map[t.id] = json.loads(t.extras_json or "{}") or {}
        except Exception:
            extras_map[t.id] = {}
    
    base_url = BASE_URL.rstrip("/")
    if not base_url:
        base_url = f"{request.url.scheme}://{request.url.hostname}" + (f":{request.url.port}" if request.url.port else "")
    return templates.TemplateResponse("admin_home.html", {"request": request, "token": token, "tasks": tasks, "staff": staff, "apartments": apts, "apt_map": apt_map, "book_map": book_map, "booking_details_map": booking_details_map, "timelog_map": timelog_map, "extras_map": extras_map, "base_url": base_url, "lang": lang, "trans": trans, "show_done": show_done, "show_open": show_open})

@app.get("/admin/{token}/staff")
async def admin_staff(request: Request, token: str, db=Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403)
    lang = detect_language(request)
    trans = get_translations(lang)
    staff = db.query(Staff).order_by(Staff.name).all()
    
    # Berechne Stunden für jeden Mitarbeiter (vorletzter, letzter, aktueller Monat)
    today = dt.date.today()
    current_month = today.strftime("%Y-%m")
    
    # Berechne vorletzten und letzten Monat
    if today.month >= 3:
        last_month = (today.year, today.month - 1)
        prev_last_month = (today.year, today.month - 2)
    elif today.month == 2:
        last_month = (today.year, 1)
        prev_last_month = (today.year - 1, 12)
    else:  # today.month == 1
        last_month = (today.year - 1, 12)
        prev_last_month = (today.year - 1, 11)
    
    last_month_str = f"{last_month[0]}-{last_month[1]:02d}"
    prev_last_month_str = f"{prev_last_month[0]}-{prev_last_month[1]:02d}"
    
    staff_hours = {}
    for s in staff:
        # Hole alle TimeLog-Einträge für diesen Mitarbeiter mit actual_minutes
        logs = db.query(TimeLog).filter(
            TimeLog.staff_id == s.id,
            TimeLog.actual_minutes != None
        ).all()
        
        hours_data = {
            'prev_last_month': 0.0,
            'last_month': 0.0,
            'current_month': 0.0
        }
        
        for tl in logs:
            if not tl.started_at:
                continue
            
            # Extrahiere Monat aus started_at (Format: "yyyy-mm-dd HH:MM:SS")
            month_str = tl.started_at[:7]  # "yyyy-mm"
            minutes = int(tl.actual_minutes or 0)
            hours = round(minutes / 60.0, 2)
            
            if month_str == prev_last_month_str:
                hours_data['prev_last_month'] += hours
            elif month_str == last_month_str:
                hours_data['last_month'] += hours
            elif month_str == current_month:
                hours_data['current_month'] += hours
        
        # Runde auf 2 Dezimalstellen
        hours_data['prev_last_month'] = round(hours_data['prev_last_month'], 2)
        hours_data['last_month'] = round(hours_data['last_month'], 2)
        hours_data['current_month'] = round(hours_data['current_month'], 2)
        
        staff_hours[s.id] = hours_data
    
    base_url = BASE_URL.rstrip("/")
    if not base_url:
        base_url = f"{request.url.scheme}://{request.url.hostname}" + (f":{request.url.port}" if request.url.port else "")
    return templates.TemplateResponse("admin_staff.html", {"request": request, "token": token, "staff": staff, "staff_hours": staff_hours, "current_month": current_month, "last_month": last_month_str, "prev_last_month": prev_last_month_str, "base_url": base_url, "lang": lang, "trans": trans})

@app.post("/admin/{token}/staff/add")
async def admin_staff_add(token: str, name: str = Form(...), email: str = Form(...), phone: str = Form(""), hourly_rate: float = Form(0.0), max_hours_per_month: int = Form(160), language: str = Form("de"), db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    email = (email or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="E-Mail ist erforderlich")
    if language not in ["de","en","fr","it","es","ro","ru","bg"]:
        language = "de"
    phone = (phone or "").strip()
    s = Staff(name=name, email=email, phone=phone, hourly_rate=hourly_rate, max_hours_per_month=max_hours_per_month, magic_token=new_token(16), active=True, language=language)
    db.add(s); db.commit()
    return RedirectResponse(url=f"/admin/{token}/staff", status_code=303)

@app.post("/admin/{token}/staff/toggle")
async def admin_staff_toggle(token: str, staff_id: int = Form(...), db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    s = db.get(Staff, staff_id); s.active = not s.active; db.commit()
    return RedirectResponse(url=f"/admin/{token}/staff", status_code=303)

@app.post("/admin/{token}/staff/update")
async def admin_staff_update(
    token: str,
    staff_id: int = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(""),
    hourly_rate: float = Form(0.0),
    max_hours_per_month: int = Form(160),
    language: str = Form("de"),
    db=Depends(get_db)
):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403)
    s = db.get(Staff, staff_id)
    if not s:
        raise HTTPException(status_code=404, detail="Staff nicht gefunden")
    email = (email or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Ungültige E-Mail")
    if language not in ["de","en","fr","it","es","ro","ru","bg"]:
        language = "de"
    phone = (phone or "").strip()
    s.name = name
    s.email = email
    s.phone = phone
    s.hourly_rate = float(hourly_rate or 0)
    s.max_hours_per_month = int(max_hours_per_month or 0)
    s.language = language
    db.commit()
    return RedirectResponse(url=f"/admin/{token}/staff", status_code=303)

@app.post("/admin/{token}/staff/delete")
async def admin_staff_delete(token: str, staff_id: int = Form(...), db=Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403)
    s = db.get(Staff, staff_id)
    if not s:
        raise HTTPException(status_code=404, detail="Staff nicht gefunden")
    # Entkopple Aufgaben
    for t in db.query(Task).filter(Task.assigned_staff_id==s.id).all():
        t.assigned_staff_id = None
        t.assignment_status = None
    # Lösche TimeLogs des Mitarbeiters
    for tl in db.query(TimeLog).filter(TimeLog.staff_id==s.id).all():
        db.delete(tl)
    db.delete(s)
    db.commit()
    return RedirectResponse(url=f"/admin/{token}/staff", status_code=303)

@app.post("/admin/{token}/task/assign")
async def admin_task_assign(request: Request, token: str, task_id: int = Form(...), staff_id_raw: str = Form(""), db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task nicht gefunden")
    prev_staff_id = t.assigned_staff_id
    staff_id: Optional[int] = int(staff_id_raw) if staff_id_raw.strip() else None
    t.assigned_staff_id = staff_id
    # Setze assignment_status auf "pending" wenn ein MA zugewiesen wird, sonst None
    if staff_id:
        t.assignment_status = "pending"
        # Markiere für Benachrichtigung
        t.assign_notified_at = None
    else:
        t.assignment_status = None
    db.commit()
    # Sofortige Mail bei neuer/ändernder Zuweisung
    try:
        if staff_id and staff_id != prev_staff_id:
            send_assignment_emails_job()
    except Exception as e:
        log.error("Immediate notify failed for task %s: %s", t.id, e)
    # Behalte Filter-Parameter bei
    referer = request.headers.get("referer", "")
    if referer:
        try:
            from urllib.parse import urlparse, parse_qs, urlencode
            parsed = urlparse(referer)
            params = parse_qs(parsed.query)
            query_parts = []
            if params.get("show_done"):
                query_parts.append(f"show_done={params['show_done'][0]}")
            if params.get("show_open"):
                query_parts.append(f"show_open={params['show_open'][0]}")
            if query_parts:
                return RedirectResponse(url=f"/admin/{token}?{'&'.join(query_parts)}", status_code=303)
        except Exception:
            pass
    return RedirectResponse(url=f"/admin/{token}", status_code=303)

@app.post("/admin/{token}/task/create")
async def admin_task_create(token: str, date: str = Form(...), apartment_id_raw: str = Form(""), planned_minutes: int = Form(90), description: str = Form(""), staff_id_raw: str = Form(""), db=Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403)
    
    # Validierung
    if not date or not date.strip():
        raise HTTPException(status_code=400, detail="Datum ist erforderlich")
    
    # Apartment-ID optional - kann leer sein für manuelle Aufgaben
    apartment_id: Optional[int] = None
    apt_name = "Manuelle Aufgabe"
    if apartment_id_raw and apartment_id_raw.strip():
        try:
            apartment_id = int(apartment_id_raw)
            if apartment_id > 0:
                apt = db.get(Apartment, apartment_id)
                if apt:
                    apt_name = apt.name
                else:
                    apartment_id = None  # Ungültige Apartment-ID ignorieren
            else:
                apartment_id = None  # 0 oder negativ = keine Apartment
        except (ValueError, TypeError):
            apartment_id = None
    
    # Staff-ID optional
    staff_id: Optional[int] = None
    if staff_id_raw and staff_id_raw.strip():
        try:
            staff_id = int(staff_id_raw)
            staff = db.get(Staff, staff_id)
            if not staff:
                staff_id = None  # Ungültige Staff-ID ignorieren
        except ValueError:
            staff_id = None
    
    # Neue Aufgabe erstellen
    new_task = Task(
        date=date[:10],  # Nur Datum, ohne Zeit
        apartment_id=apartment_id,  # Kann None sein für manuelle Aufgaben
        planned_minutes=planned_minutes,
        notes=(description[:2000] if description else None),  # Beschreibung als Notiz speichern
        assigned_staff_id=staff_id,
        assignment_status="pending" if staff_id else None,
        status="open",
        auto_generated=False  # Manuell erstellt
    )
    db.add(new_task)
    db.commit()
    
    log.info("✅ Manuell erstellte Aufgabe: %s für %s am %s", new_task.id, apt_name, date)
    return RedirectResponse(url=f"/admin/{token}", status_code=303)

@app.post("/admin/{token}/task/delete")
async def admin_task_delete(token: str, task_id: int = Form(...), db=Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task nicht gefunden")
    if t.auto_generated:
        raise HTTPException(status_code=400, detail="Automatisch erzeugte Aufgaben können hier nicht gelöscht werden")
    for tl in db.query(TimeLog).filter(TimeLog.task_id==t.id).all():
        db.delete(tl)
    db.delete(t)
    db.commit()
    return RedirectResponse(url=f"/admin/{token}", status_code=303)

@app.post("/admin/{token}/task/status")
async def admin_task_status(token: str, task_id: int = Form(...), status: str = Form(...), db=Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403)
    allowed = {"open", "paused", "done"}
    status = (status or "").strip().lower()
    if status not in allowed:
        raise HTTPException(status_code=400, detail="Ungültiger Status")
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task nicht gefunden")
    # TimeLogs behandeln: offene Logs schließen, wenn nicht 'running'
    tl = db.query(TimeLog).filter(TimeLog.task_id==t.id, TimeLog.ended_at==None).order_by(TimeLog.id.desc()).first()
    if tl:
        from datetime import datetime
        fmt = "%Y-%m-%d %H:%M:%S"
        tl.ended_at = now_iso()
        try:
            start = datetime.strptime(tl.started_at, fmt)
            end = datetime.strptime(tl.ended_at, fmt)
            elapsed = int((end-start).total_seconds()//60)
            tl.actual_minutes = int(tl.actual_minutes or 0) + max(0, elapsed)
        except Exception:
            pass
    t.status = status
    db.commit()
    return RedirectResponse(url=f"/admin/{token}", status_code=303)


@app.post("/admin/{token}/task/extras")
async def admin_task_extras(
    request: Request,
    token: str,
    task_id: int = Form(...),
    field: str = Form(...),
    value: str = Form("0"),
    redirect: str = Form(""),
    db=Depends(get_db),
):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403)
    allowed_fields = {"kurtaxe_registriert", "kurtaxe_bestaetigt", "checkin_vorbereitet", "kurtaxe_bezahlt", "baby_beds"}
    field = (field or "").strip()
    if field not in allowed_fields:
        raise HTTPException(status_code=400, detail="Ungültiges Feld")
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task nicht gefunden")
    try:
        extras = json.loads(t.extras_json or "{}") or {}
    except Exception:
        extras = {}
    value_str = (value or "").strip().lower()
    if field == "baby_beds":
        try:
            beds = int(value_str)
        except ValueError:
            beds = 0
        beds = max(0, min(2, beds))
        extras[field] = beds
        response_value = beds
    else:
        flag = value_str in {"1", "true", "yes", "on"}
        extras[field] = flag
        response_value = flag
    t.extras_json = json.dumps(extras)
    db.commit()
    if (request.headers.get("x-requested-with") or "").lower() == "fetch":
        return JSONResponse({"ok": True, "task_id": t.id, "field": field, "value": response_value})
    target = redirect or request.headers.get("referer") or f"/admin/{token}"
    return RedirectResponse(url=target, status_code=303)

@app.get("/admin/{token}/apartments")
async def admin_apartments(request: Request, token: str, db=Depends(get_db)):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403)
    lang = detect_language(request)
    trans = get_translations(lang)
    apts = db.query(Apartment).order_by(Apartment.name).all()
    return templates.TemplateResponse("admin_apartments.html", {"request": request, "token": token, "apartments": apts, "lang": lang, "trans": trans})

@app.post("/admin/{token}/apartments/update")
async def admin_apartments_update(token: str, apartment_id: int = Form(...), planned_minutes: int = Form(...), db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    a = db.get(Apartment, apartment_id)
    a.planned_minutes = int(planned_minutes)
    db.commit()
    return RedirectResponse(url=f"/admin/{token}/apartments", status_code=303)

@app.post("/admin/{token}/apartments/apply")
async def admin_apartments_apply(token: str, apartment_id: int = Form(...), db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    a = db.get(Apartment, apartment_id)
    if not a:
        raise HTTPException(status_code=404, detail="Apartment nicht gefunden")
    
    # Get today's date
    today_iso = dt.date.today().isoformat()
    
    # Update all tasks for this apartment that are today or in the future
    tasks = db.query(Task).filter(
        Task.apartment_id == apartment_id,
        Task.date >= today_iso
    ).all()
    
    updated = 0
    for t in tasks:
        t.planned_minutes = a.planned_minutes
        # Benachrichtigung bei geänderter Dauer für zugewiesene (bündeln via Scheduler)
        if t.assigned_staff_id and t.assignment_status != "rejected":
            t.assign_notified_at = None
        updated += 1
    
    db.commit()
    log.info("Updated %d tasks for apartment %s to %d minutes", updated, a.name, a.planned_minutes)
    return RedirectResponse(url=f"/admin/{token}/apartments", status_code=303)

@app.get("/admin/{token}/import")
async def admin_import(token: str, db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    await refresh_bookings_job()
    return PlainTextResponse("Import done.")

@app.get("/admin/{token}/test_whatsapp")
async def admin_test_whatsapp(token: str, phone: str = Query(...), db=Depends(get_db)):
    """Test WhatsApp-Versand"""
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403)
    
    test_msg = "🧪 Test-Nachricht von Staff Planner"
    
    config_status = {
        "TWILIO_ACCOUNT_SID": "✅ gesetzt" if TWILIO_ACCOUNT_SID else "❌ nicht gesetzt",
        "TWILIO_AUTH_TOKEN": "✅ gesetzt" if TWILIO_AUTH_TOKEN else "❌ nicht gesetzt",
        "TWILIO_WHATSAPP_FROM": TWILIO_WHATSAPP_FROM if TWILIO_WHATSAPP_FROM else "❌ nicht gesetzt",
    }
    
    try:
        from twilio.rest import Client
        twilio_installed = "✅ installiert"
    except ImportError:
        twilio_installed = "❌ nicht installiert"
        return PlainTextResponse(f"❌ Twilio Library nicht installiert")
    
    # Versuche Nachricht zu senden und hole Details
    result = False
    message_details = {}
    normalized_phone = phone
    whatsapp_to = ""
    try:
        # Normalisiere Telefonnummer wie in _send_whatsapp
        normalized_phone = phone.strip().replace(" ", "").replace("-", "")
        if not normalized_phone.startswith("+"):
            if normalized_phone.startswith("0"):
                normalized_phone = "+49" + normalized_phone[1:]
            else:
                normalized_phone = "+49" + normalized_phone
        whatsapp_to = f"whatsapp:{normalized_phone}"
        
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        message_obj = client.messages.create(
            body=test_msg,
            from_=TWILIO_WHATSAPP_FROM,
            to=whatsapp_to
        )
        message_details = {
            "sid": message_obj.sid,
            "status": getattr(message_obj, 'status', 'unknown'),
            "error_code": getattr(message_obj, 'error_code', None),
            "error_message": getattr(message_obj, 'error_message', None),
            "price": getattr(message_obj, 'price', None),
            "price_unit": getattr(message_obj, 'price_unit', None),
        }
        result = message_details['status'] in ['queued', 'sent', 'delivered']
    except Exception as e:
        message_details = {"error": str(e)}
    
    response_text = (
        f"WhatsApp Test\n"
        f"=============\n\n"
        f"Telefonnummer (Eingabe): {phone}\n"
        f"Telefonnummer (normalisiert): {normalized_phone}\n"
        f"WhatsApp To: {whatsapp_to}\n\n"
        f"Ergebnis: {'✅ Erfolgreich' if result else '❌ Fehlgeschlagen'}\n\n"
        f"Message Details:\n"
        f"- SID: {message_details.get('sid', 'N/A')}\n"
        f"- Status: {message_details.get('status', 'N/A')}\n"
        f"- Error Code: {message_details.get('error_code', 'N/A')}\n"
        f"- Error Message: {message_details.get('error_message', 'N/A')}\n"
        f"- Price: {message_details.get('price', 'N/A')} {message_details.get('price_unit', '')}\n\n"
        f"Konfiguration:\n"
        f"- Twilio Library: {twilio_installed}\n"
        f"- Account SID: {config_status['TWILIO_ACCOUNT_SID']}\n"
        f"- Auth Token: {config_status['TWILIO_AUTH_TOKEN']}\n"
        f"- WhatsApp From: {config_status['TWILIO_WHATSAPP_FROM']}\n\n"
        f"Hinweis: Wenn Status 'queued' ist, wurde die Nachricht an Twilio gesendet.\n"
        f"Falls keine Nachricht ankommt, prüfe:\n"
        f"1. Ist die Nummer bei Twilio WhatsApp Sandbox verifiziert?\n"
        f"2. Ist TWILIO_WHATSAPP_FROM korrekt formatiert (whatsapp:+14155238886)?\n"
        f"3. Prüfe Twilio Console für Delivery-Status: https://console.twilio.com/\n"
    )
    
    return PlainTextResponse(response_text)

@app.get("/admin/{token}/notify_assignments")
async def admin_notify_assignments(token: str):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403)
    try:
        report = send_assignment_emails_job()
        if not report:
            return PlainTextResponse("Keine offenen Zuweisungen zum Versenden.")
        # Baue menschenlesbaren Report
        lines = ["Benachrichtigungen gesendet:", ""]
        for r in report:
            lines.append(f"- {r['staff_name']} <{r['email']}>: {r['count']} Aufgaben")
            for it in r['items']:
                guest = f" · {it['guest']}" if it.get('guest') else ""
                lines.append(f"  • {it['date']} · {it['apt']} · {it['desc']}{guest}")
            lines.append("")
        return PlainTextResponse("\n".join(lines).strip())
    except Exception as e:
        log.exception("Manual notify failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/{token}/cleanup_tasks")
async def admin_cleanup_tasks(token: str, date: str, db=Depends(get_db)):
    """Manuelles Löschen von Tasks an einem bestimmten Datum"""
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    
    removed_count = 0
    tasks = db.query(Task).filter(Task.date == date, Task.auto_generated == True).all()
    
    for t in tasks:
        db.delete(t)
        removed_count += 1
        log.info("Removed task %d for date %s (apartment: %s)", t.id, date, t.apartment_id)
    
    db.commit()
    return PlainTextResponse(f"Removed {removed_count} tasks for date {date}.")

@app.get("/admin/{token}/cleanup")
async def admin_cleanup(token: str, db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    
    removed_count = 0
    all_bookings = {b.id for b in db.query(Booking).all()}
    log.info("🔍 Cleanup started. Checking %d tasks against %d bookings", db.query(Task).count(), len(all_bookings))
    
    # Finde ALLE ungültigen Tasks
    for t in db.query(Task).all():
        should_delete = False
        reason = ""
        
        # Nur auto-generierte Tasks prüfen
        if t.auto_generated and t.booking_id:
            b = db.get(Booking, t.booking_id)
            
            # Wenn Buchung nicht mehr existiert
            if not b or t.booking_id not in all_bookings:
                should_delete = True
                reason = f"booking {t.booking_id} does not exist"
            # Wenn Buchung kein departure hat
            elif not b.departure or not b.departure.strip():
                should_delete = True
                reason = f"booking {t.booking_id} has no departure"
            # Wenn Buchung kein arrival hat
            elif not b.arrival or not b.arrival.strip():
                should_delete = True
                reason = f"booking {t.booking_id} has no arrival"
            # Wenn departure format ungültig
            elif len(b.departure) != 10 or b.departure.count('-') != 2:
                should_delete = True
                reason = f"booking {t.booking_id} has invalid departure format"
            # Wenn arrival format ungültig
            elif len(b.arrival) != 10 or b.arrival.count('-') != 2:
                should_delete = True
                reason = f"booking {t.booking_id} has invalid arrival format"
            # Wenn departure <= arrival
            elif b.departure <= b.arrival:
                should_delete = True
                reason = f"booking {t.booking_id} departure <= arrival"
        
        if should_delete:
            db.delete(t)
            removed_count += 1
            log.info("🗑️ Removing invalid task %d (date: %s, apt: %s, booking: %s) - %s", t.id, t.date, t.apartment_id, t.booking_id, reason)
    
    db.commit()
    log.info("✅ Cleanup done. Removed %d invalid tasks", removed_count)
    return PlainTextResponse(f"Cleanup done. Removed {removed_count} invalid tasks. Check logs for details.")

@app.get("/admin/{token}/export")
async def admin_export(token: str, month: str, db=Depends(get_db)):
    if token != ADMIN_TOKEN: raise HTTPException(status_code=403)
    apts = db.query(Apartment).all()
    apt_map = {a.id: a.name for a in apts}
    rows = []
    for t in db.query(Task).order_by(Task.date, Task.id).all():
        if not t.date.startswith(month): continue
        staff = db.get(Staff, t.assigned_staff_id) if t.assigned_staff_id else None
        rate = float(staff.hourly_rate) if staff else 0.0
        actual = 0
        tl = db.query(TimeLog).filter(TimeLog.task_id==t.id, TimeLog.actual_minutes!=None).order_by(TimeLog.id.desc()).first()
        if tl: actual = int(tl.actual_minutes)
        cost = round((actual/60.0)*rate, 2)
        rows.append({
            "date": t.date,
            "apartment_id": t.apartment_id,
            "apartment_name": apt_map.get(t.apartment_id, ""),
            "staff": staff.name if staff else "",
            "planned_minutes": t.planned_minutes,
            "actual_minutes": actual,
            "hourly_rate": rate,
            "cost_eur": cost,
            "notes": t.notes,
            "extras": t.extras_json,
            "next_arrival": t.next_arrival or "",
            "next_arrival_adults": t.next_arrival_adults or 0,
            "next_arrival_children": t.next_arrival_children or 0,
        })
    headers = list(rows[0].keys()) if rows else ["date","apartment_id","apartment_name","staff","planned_minutes","actual_minutes","hourly_rate","cost_eur","notes","extras","next_arrival","next_arrival_adults","next_arrival_children"]
    output = io.StringIO()
    w = csv.DictWriter(output, fieldnames=headers)
    w.writeheader()
    for r in rows: w.writerow(r)
    return StreamingResponse(iter([output.getvalue().encode('utf-8')]), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=report-{month}.csv"})

# -------------------- Cleaner --------------------
@app.get("/cleaner/{token}")
async def cleaner_home(request: Request, token: str, show_done: int = 1, show_open: int = 1, db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    q = db.query(Task).filter(Task.assigned_staff_id==s.id)
    # Abgelehnte Tasks ausblenden - zeige nur Tasks die nicht rejected sind
    from sqlalchemy import or_
    q = q.filter(or_(Task.assignment_status != "rejected", Task.assignment_status.is_(None)))
    # Filter nach Status: erledigte und/oder offene Aufgaben
    status_filters = []
    if show_done:
        status_filters.append(Task.status == "done")
    if show_open:
        status_filters.append(Task.status != "done")
    if status_filters:
        q = q.filter(or_(*status_filters))
    else:
        # Wenn beide Filter deaktiviert sind, zeige nichts
        q = q.filter(Task.id == -1)  # Unmögliche Bedingung
    tasks = q.order_by(Task.date, Task.id).all()
    apts = db.query(Apartment).all()
    apt_map = {a.id: a.name for a in apts}
    bookings = db.query(Booking).all()
    book_map = {b.id: (b.guest_name or "").strip() for b in bookings if b.guest_name}
    booking_details_map = {b.id: {'adults': b.adults or 0, 'children': b.children or 0, 'guest_name': (b.guest_name or "").strip()} for b in bookings}
    # Stunden: vorletzter, letzter, aktueller Monat
    today = dt.date.today()
    current_month_str = today.strftime("%Y-%m")
    if today.month >= 3:
        last_month = (today.year, today.month - 1)
        prev_last_month = (today.year, today.month - 2)
    elif today.month == 2:
        last_month = (today.year, 1)
        prev_last_month = (today.year - 1, 12)
    else:  # today.month == 1
        last_month = (today.year - 1, 12)
        prev_last_month = (today.year - 1, 11)
    last_month_str = f"{last_month[0]}-{last_month[1]:02d}"
    prev_last_month_str = f"{prev_last_month[0]}-{prev_last_month[1]:02d}"

    logs = db.query(TimeLog).filter(TimeLog.staff_id==s.id, TimeLog.actual_minutes!=None).all()
    minutes_current = 0
    minutes_last = 0
    minutes_prev_last = 0
    for tl in logs:
        if not tl.started_at:
            continue
        m = tl.started_at[:7]
        mins = int(tl.actual_minutes or 0)
        if m == current_month_str:
            minutes_current += mins
        elif m == last_month_str:
            minutes_last += mins
        elif m == prev_last_month_str:
            minutes_prev_last += mins
    hours_current = round(minutes_current/60.0, 2)
    hours_last = round(minutes_last/60.0, 2)
    hours_prev_last = round(minutes_prev_last/60.0, 2)
    used_hours = hours_current
    run_map: Dict[int, str] = {}
    for t in tasks:
        tl = db.query(TimeLog).filter(TimeLog.task_id==t.id, TimeLog.staff_id==s.id, TimeLog.ended_at==None).order_by(TimeLog.id.desc()).first()
        if tl:
            run_map[t.id] = tl.started_at
    has_running = any(t.status == 'running' for t in tasks)
    warn_limit = used_hours > float(s.max_hours_per_month or 0)
    # Timelog-Daten für jedes Task (für pausierte Aufgaben)
    timelog_map = {}
    for t in tasks:
        tl = db.query(TimeLog).filter(TimeLog.task_id==t.id, TimeLog.staff_id==s.id).order_by(TimeLog.id.desc()).first()
        if tl:
            timelog_map[t.id] = {
                'actual_minutes': tl.actual_minutes,
                'started_at': tl.started_at,
                'ended_at': tl.ended_at
            }
    extras_map: Dict[int, Dict[str, object]] = {}
    for t in tasks:
        try:
            extras_map[t.id] = json.loads(t.extras_json or "{}") or {}
        except Exception:
            extras_map[t.id] = {}
    lang = detect_language(request)
    trans = get_translations(lang)
    return templates.TemplateResponse("cleaner.html", {"request": request, "tasks": tasks, "used_hours": used_hours, "hours_prev_last": hours_prev_last, "hours_last": hours_last, "hours_current": hours_current, "apt_map": apt_map, "book_map": book_map, "booking_details_map": booking_details_map, "staff": s, "show_done": show_done, "show_open": show_open, "run_map": run_map, "timelog_map": timelog_map, "extras_map": extras_map, "warn_limit": warn_limit, "lang": lang, "trans": trans, "has_running": has_running})

@app.post("/cleaner/{token}/start")
async def cleaner_start(token: str, task_id: int = Form(...), show_done: Optional[int] = Form(None), show_open: Optional[int] = Form(None), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t: raise HTTPException(status_code=404, detail="Task nicht gefunden")
    
    # Beende alle offenen TimeLogs dieses Staff (außer für den aktuellen Task, falls er pausiert ist)
    open_tls = db.query(TimeLog).filter(TimeLog.staff_id==s.id, TimeLog.ended_at==None, TimeLog.task_id!=task_id).all()
    for open_tl in open_tls:
        from datetime import datetime
        open_tl.ended_at = now_iso()
        fmt = "%Y-%m-%d %H:%M:%S"
        try:
            start = datetime.strptime(open_tl.started_at, fmt)
            end = datetime.strptime(open_tl.ended_at, fmt)
            elapsed = int((end-start).total_seconds()//60)
            if open_tl.actual_minutes:
                open_tl.actual_minutes += elapsed
            else:
                open_tl.actual_minutes = elapsed
        except Exception:
            pass
        # Setze den Status der anderen Tasks auf 'open'
        other_task = db.get(Task, open_tl.task_id)
        if other_task and other_task.status == 'running':
            other_task.status = 'open'
    
    # Prüfe ob bereits ein TimeLog für diesen Task existiert (pausierte Aufgabe)
    existing_tl = db.query(TimeLog).filter(TimeLog.task_id==task_id, TimeLog.staff_id==s.id, TimeLog.ended_at==None).order_by(TimeLog.id.desc()).first()
    if existing_tl:
        # Setze started_at auf jetzt, damit die Zeit weiterläuft
        existing_tl.started_at = now_iso()
    else:
        # Erstelle neues TimeLog für diesen Task
        existing_tl = TimeLog(task_id=task_id, staff_id=s.id, started_at=now_iso(), ended_at=None, actual_minutes=None)
        db.add(existing_tl)
    
    t.status = "running"
    db.commit()
    # Behalte Filter-Parameter bei
    query_string = ""
    if show_done is not None or show_open is not None:
        query_parts = []
        if show_done is not None:
            query_parts.append(f"show_done={show_done}")
        if show_open is not None:
            query_parts.append(f"show_open={show_open}")
        if query_parts:
            query_string = "?" + "&".join(query_parts)
    return RedirectResponse(url=f"/cleaner/{token}{query_string}", status_code=303)

@app.post("/cleaner/{token}/stop")
async def cleaner_stop(token: str, task_id: int = Form(...), show_done: Optional[int] = Form(None), show_open: Optional[int] = Form(None), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t: raise HTTPException(status_code=404, detail="Task nicht gefunden")
    
    tl = db.query(TimeLog).filter(TimeLog.task_id==task_id, TimeLog.staff_id==s.id, TimeLog.ended_at==None).order_by(TimeLog.id.desc()).first()
    if tl:
        from datetime import datetime
        fmt = "%Y-%m-%d %H:%M:%S"
        # Speichere aktuelle Zeit, aber lasse ended_at auf None für spätere Fortsetzung
        # Berechne die bisherige Zeit
        try:
            start = datetime.strptime(tl.started_at, fmt)
            now = datetime.now()
            # Berechne bisherige Minuten und addiere zu eventuell bereits vorhandenen
            current_elapsed = int((now - start).total_seconds() // 60)
            if tl.actual_minutes:
                tl.actual_minutes += current_elapsed
            else:
                tl.actual_minutes = current_elapsed
            # Aktualisiere started_at auf jetzt, damit beim Weiterstarten die Zeit korrekt weiterläuft
            tl.started_at = now_iso()
            # Lassen ended_at auf None, damit wir wissen dass es pausiert ist
        except Exception as e:
            log.error("Error in cleaner_stop: %s", e)
            pass
    
    t.status = "paused"  # Status auf "paused" setzen statt "open"
    db.commit()
    # Behalte Filter-Parameter bei
    query_string = ""
    if show_done is not None or show_open is not None:
        query_parts = []
        if show_done is not None:
            query_parts.append(f"show_done={show_done}")
        if show_open is not None:
            query_parts.append(f"show_open={show_open}")
        if query_parts:
            query_string = "?" + "&".join(query_parts)
    return RedirectResponse(url=f"/cleaner/{token}{query_string}", status_code=303)

@app.post("/cleaner/{token}/done")
async def cleaner_done(token: str, task_id: int = Form(...), show_done: Optional[int] = Form(None), show_open: Optional[int] = Form(None), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t: raise HTTPException(status_code=404, detail="Task nicht gefunden")
    
    # Beende TimeLog wenn noch offen
    tl = db.query(TimeLog).filter(TimeLog.task_id==task_id, TimeLog.staff_id==s.id, TimeLog.ended_at==None).order_by(TimeLog.id.desc()).first()
    if tl:
        from datetime import datetime
        fmt = "%Y-%m-%d %H:%M:%S"
        tl.ended_at = now_iso()
        try:
            start = datetime.strptime(tl.started_at, fmt)
            end = datetime.strptime(tl.ended_at, fmt)
            tl.actual_minutes = int((end-start).total_seconds()//60)
        except Exception:
            pass
    
    t.status = "done"
    db.commit()
    # Behalte Filter-Parameter bei
    query_string = ""
    if show_done is not None or show_open is not None:
        query_parts = []
        if show_done is not None:
            query_parts.append(f"show_done={show_done}")
        if show_open is not None:
            query_parts.append(f"show_open={show_open}")
        if query_parts:
            query_string = "?" + "&".join(query_parts)
    return RedirectResponse(url=f"/cleaner/{token}{query_string}", status_code=303)

@app.post("/cleaner/{token}/accept")
async def cleaner_accept(token: str, task_id: int = Form(...), show_done: Optional[int] = Form(None), show_open: Optional[int] = Form(None), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t or t.assigned_staff_id != s.id:
        raise HTTPException(status_code=404, detail="Task nicht gefunden oder nicht zugewiesen")
    t.assignment_status = "accepted"
    db.commit()
    # Behalte Filter-Parameter bei
    query_string = ""
    if show_done is not None or show_open is not None:
        query_parts = []
        if show_done is not None:
            query_parts.append(f"show_done={show_done}")
        if show_open is not None:
            query_parts.append(f"show_open={show_open}")
        if query_parts:
            query_string = "?" + "&".join(query_parts)
    return RedirectResponse(url=f"/cleaner/{token}{query_string}", status_code=303)

@app.post("/cleaner/{token}/reject")
async def cleaner_reject(token: str, task_id: int = Form(...), show_done: Optional[int] = Form(None), show_open: Optional[int] = Form(None), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t or t.assigned_staff_id != s.id:
        raise HTTPException(status_code=404, detail="Task nicht gefunden oder nicht zugewiesen")
    t.assignment_status = "rejected"
    db.commit()
    # Behalte Filter-Parameter bei
    query_string = ""
    if show_done is not None or show_open is not None:
        query_parts = []
        if show_done is not None:
            query_parts.append(f"show_done={show_done}")
        if show_open is not None:
            query_parts.append(f"show_open={show_open}")
        if query_parts:
            query_string = "?" + "&".join(query_parts)
    return RedirectResponse(url=f"/cleaner/{token}{query_string}", status_code=303)

@app.post("/cleaner/{token}/reopen")
async def cleaner_reopen(token: str, task_id: int = Form(...), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    tl = db.query(TimeLog).filter(TimeLog.task_id==task_id, TimeLog.staff_id==s.id).order_by(TimeLog.id.desc()).first()
    if tl:
        db.delete(tl)
    t.status = "open"
    db.commit()
    return RedirectResponse(url=f"/cleaner/{token}?show_done=1", status_code=303)

@app.post("/cleaner/{token}/note")
async def cleaner_note(token: str, task_id: int = Form(...), note: str = Form(""), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    t.notes = (note or "").strip()
    db.commit()
    return JSONResponse({"ok": True, "task_id": t.id, "note": t.notes})

@app.post("/cleaner/{token}/task/create")
async def cleaner_task_create(token: str, date: str = Form(...), planned_minutes: int = Form(90), description: str = Form(""), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s:
        raise HTTPException(status_code=403)
    # Validierung
    if not date or not date.strip():
        raise HTTPException(status_code=400, detail="Datum ist erforderlich")
    try:
        _ = dt.datetime.strptime(date[:10], "%Y-%m-%d")
    except Exception:
        raise HTTPException(status_code=400, detail="Ungültiges Datum")
    pm = int(planned_minutes or 0)
    if pm <= 0:
        pm = 30
    # Manuelle Aufgabe, dem Cleaner selbst zugeordnet
    t = Task(
        date=date[:10],
        apartment_id=None,
        planned_minutes=pm,
        notes=(description[:2000] if description else None),
        assigned_staff_id=s.id,
        assignment_status="accepted",
        status="open",
        auto_generated=False
    )
    db.add(t)
    db.commit()
    return RedirectResponse(url=f"/cleaner/{token}", status_code=303)

@app.post("/cleaner/{token}/task/delete")
async def cleaner_task_delete(token: str, task_id: int = Form(...), db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s:
        raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t or t.assigned_staff_id != s.id:
        raise HTTPException(status_code=404, detail="Task nicht gefunden oder nicht zugewiesen")
    if t.auto_generated:
        raise HTTPException(status_code=400, detail="Automatisch erzeugte Aufgaben können hier nicht gelöscht werden")
    # Timelogs für diesen Task entfernen
    for tl in db.query(TimeLog).filter(TimeLog.task_id==t.id).all():
        db.delete(tl)
    db.delete(t)
    db.commit()
    return RedirectResponse(url=f"/cleaner/{token}", status_code=303)

@app.get("/c/{token}/accept")
async def cleaner_accept_get(token: str, task_id: int, db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t or t.assigned_staff_id != s.id:
        raise HTTPException(status_code=404, detail="Task nicht gefunden oder nicht zugewiesen")
    t.assignment_status = "accepted"
    db.commit()
    return RedirectResponse(url=f"/cleaner/{token}", status_code=303)

@app.get("/c/{token}/reject")
async def cleaner_reject_get(token: str, task_id: int, db=Depends(get_db)):
    s = db.query(Staff).filter(Staff.magic_token==token, Staff.active==True).first()
    if not s: raise HTTPException(status_code=403)
    t = db.get(Task, task_id)
    if not t or t.assigned_staff_id != s.id:
        raise HTTPException(status_code=404, detail="Task nicht gefunden oder nicht zugewiesen")
    t.assignment_status = "rejected"
    db.commit()
    return RedirectResponse(url=f"/cleaner/{token}", status_code=303)
