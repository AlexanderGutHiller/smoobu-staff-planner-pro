import os, json, datetime as dt, csv, io, logging
from typing import List, Optional, Dict
from fastapi import FastAPI, Request, Depends, Form, HTTPException, Query
from fastapi.responses import RedirectResponse, StreamingResponse, PlainTextResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import date as _date, datetime as _dt, timedelta as _td
from pywebpush import webpush, WebPushException

from .db import init_db, SessionLocal
from .models import Booking, Staff, Apartment, Task, TimeLog, TaskSeries, PushSubscription
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

# Import configuration from config.py
from .config import (
    ADMIN_TOKEN, TIMEZONE, REFRESH_INTERVAL_MINUTES, BASE_URL,
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM,
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, TWILIO_WHATSAPP_CONTENT_SID,
    APP_VERSION, APP_BUILD_DATE, VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_EMAIL
)
from .shared import templates

log = logging.getLogger("smoobu")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Smoobu Staff Planner Pro (v6.3)")

# Register routers
from .routers import main as main_router, admin as admin_router, cleaner as cleaner_router, webhooks as webhooks_router, push as push_router
app.include_router(main_router.router)
app.include_router(admin_router.router)
app.include_router(cleaner_router.router)
app.include_router(cleaner_router.router_short)
app.include_router(webhooks_router.router)
app.include_router(push_router.router)
app.include_router(push_router.router_admin)

if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Service Worker aus static bereitstellen (Fallback, falls kein static-Ordner)
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
    # Expand recurring TaskSeries daily
    scheduler.add_job(expand_series_job, IntervalTrigger(hours=24))
    scheduler.start()

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

# Helper functions for date parsing and series expansion
def _parse_date(s: str) -> _date | None:
    try:
        return _dt.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def _add_months(d: _date, months: int) -> _date:
    # simple month addition handling year wrap and end-of-month
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    # clamp day to last day of target month
    import calendar
    last_day = calendar.monthrange(y, m)[1]
    day = min(d.day, last_day)
    return _date(y, m, day)

def _daterange_iter(start: _date, end: _date):
    cur = start
    while cur <= end:
        yield cur
        cur = cur + _td(days=1)

def _expand_series_occurrences(series: TaskSeries, start_from: _date, until: _date) -> list[_date]:
    """Return list of dates to generate between start_from and until inclusive."""
    out: list[_date] = []
    if not series.active:
        return out
    s0 = _parse_date(series.start_date)
    if not s0:
        return out
    end_limit = _parse_date(series.end_date) if series.end_date else None
    hard_until = min(until, end_limit) if end_limit else until
    if hard_until < start_from:
        return out
    freq = (series.frequency or "").lower()
    interval = max(1, int(series.interval or 1))
    if freq == "weekly":
        # determine weekdays
        wd_map = {"mo":0,"tu":1,"we":2,"th":3,"fr":4,"sa":5,"su":6}
        if series.byweekday:
            wds = [wd_map.get(p.strip().lower()[:2]) for p in series.byweekday.split(",")]
            wds = [w for w in wds if w is not None]
            if not wds:
                wds = [s0.weekday()]
        else:
            wds = [s0.weekday()]
        # find the first week start aligned to interval
        # compute week index since start
        start_week_monday = s0 - _td(days=s0.weekday())
        for d in _daterange_iter(max(start_from, s0), hard_until):
            # check interval weeks from start
            windex = ((d - start_week_monday).days // 7)
            if windex % interval == 0 and d.weekday() in wds and d >= s0:
                out.append(d)
                if series.count and len(out) >= series.count:
                    break
    elif freq == "monthly":
        # bymonthday list or default to start day
        if series.bymonthday:
            mdays = []
            for p in series.bymonthday.split(","):
                try:
                    md = int(p.strip())
                    if 1 <= md <= 31:
                        mdays.append(md)
                except Exception:
                    pass
            if not mdays:
                mdays = [s0.day]
        else:
            mdays = [s0.day]
        # iterate months from s0 to hard_until
        cur = s0
        # set cur to first month that reaches start_from
        while cur < start_from:
            cur = _add_months(cur, interval)
        gen = 0
        while cur <= hard_until:
            import calendar
            last_day = calendar.monthrange(cur.year, cur.month)[1]
            for md in mdays:
                day = min(md, last_day)
                d = _date(cur.year, cur.month, day)
                if d < s0 or d < start_from or d > hard_until:
                    continue
                out.append(d)
                gen += 1
                if series.count and gen >= series.count:
                    return out
            cur = _add_months(cur, interval)
    elif freq == "yearly":
        cur = s0
        while cur < start_from:
            cur = _date(cur.year + interval, cur.month, cur.day)
        gen = 0
        while cur <= hard_until:
            if cur >= s0 and cur >= start_from:
                out.append(cur)
                gen += 1
                if series.count and gen >= series.count:
                    return out
            cur = _date(cur.year + interval, cur.month, cur.day)
    else:
        # unsupported; fallback: single occurrence at start_date if in window
        if s0 >= start_from and s0 <= hard_until:
            out.append(s0)
    return out

def expand_series_job(days_ahead: int = 30):
    """Generate tasks from active TaskSeries for the next days_ahead."""
    with SessionLocal() as db:
        horizon = _date.today() + _td(days=days_ahead)
        series_list = db.query(TaskSeries).filter(TaskSeries.active==True).all()
        created = 0
        new_tasks: list[Task] = []
        for ser in series_list:
            # find last generated date for this series
            last = db.query(Task).filter(Task.series_id==ser.id).order_by(Task.date.desc()).first()
            start_from = _parse_date(last.date) + _td(days=1) if last else _parse_date(ser.start_date) or _date.today()
            occ = _expand_series_occurrences(ser, start_from, horizon)
            for d in occ:
                # skip if task exists for same series+date
                exists = db.query(Task).filter(Task.series_id==ser.id, Task.date==(d.isoformat())).first()
                if exists:
                    continue
                t = Task(
                    date=d.isoformat(),
                    apartment_id=ser.apartment_id,
                    planned_minutes=ser.planned_minutes or 60,
                    notes=(ser.description or None),
                    assigned_staff_id=ser.staff_id,
                    assignment_status="pending" if ser.staff_id else None,
                    status="open",
                    auto_generated=False,
                    series_id=ser.id,
                    is_recurring=True
                )
                db.add(t)
                created += 1
                new_tasks.append(t)
        db.commit()
        # Sofort benachrichtigen, wenn neue Zuweisungen entstanden sind
        if created > 0:
            try:
                send_assignment_emails_job()
            except Exception as e:
                log.error("send_assignment_emails_job after series expansion failed: %s", e)
        log.info("🗓️ Series expansion created %d tasks up to %s", created, horizon.isoformat())
        return created

def minutes_to_hhmm(minutes: Optional[int]) -> str:
    """Konvertiere Minuten in hh:mm Format"""
    if minutes is None:
        return "--:--"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"

# Register template filters
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

def _send_whatsapp(to_phone: str, message: str, use_template: bool = False):
    """Sende WhatsApp-Nachricht über Twilio
    
    Args:
        to_phone: Telefonnummer
        message: Nachrichtentext
        use_template: Wenn True, verwende Content SID (Opt-In-Vorlage), sonst freie Nachricht
    """
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
        log.info("📱 Sending WhatsApp: from=%s, to=%s, message_length=%d, use_template=%s", 
                 TWILIO_WHATSAPP_FROM, whatsapp_to, len(message), use_template)
        
        # Status-Callback-URL für Delivery-Updates
        status_callback_url = None
        if BASE_URL:
            status_callback_url = f"{BASE_URL.rstrip('/')}/webhook/twilio/status"
        
        # Verwende WhatsApp-Vorlage (Content SID) wenn gewünscht und konfiguriert
        if use_template and TWILIO_WHATSAPP_CONTENT_SID:
            # Verwende Content SID mit Content Variables (Opt-In-Vorlage)
            # Die Nachricht wird als Variable übergeben (normalerweise {{1}} in der Vorlage)
            message_obj = client.messages.create(
                content_sid=TWILIO_WHATSAPP_CONTENT_SID,
                content_variables=json.dumps({"1": message}),  # Variable 1 enthält die Nachricht
                from_=TWILIO_WHATSAPP_FROM,
                to=whatsapp_to,
                status_callback=status_callback_url
            )
            log.info("📱 Using WhatsApp template (Content SID: %s)", TWILIO_WHATSAPP_CONTENT_SID)
        else:
            # Freie Nachricht (nur innerhalb 24h-Fenster möglich)
            message_obj = client.messages.create(
                body=message,
                from_=TWILIO_WHATSAPP_FROM,
                to=whatsapp_to,
                status_callback=status_callback_url
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

def _send_whatsapp_with_opt_in(to_phone: str, message: str, staff_id: Optional[int] = None, db=None):
    """Sende WhatsApp-Nachricht mit Opt-In-Check
    
    Wenn Opt-In noch nicht bestätigt wurde, wird nur die Opt-In-Vorlage gesendet.
    Die normale Nachricht wird erst gesendet, wenn Opt-In bestätigt wurde.
    """
    # Prüfe Opt-In-Status
    opt_in_sent = False
    opt_in_confirmed = False
    if staff_id and db:
        staff = db.get(Staff, staff_id)
        if staff:
            opt_in_sent = getattr(staff, 'whatsapp_opt_in_sent', False)
            opt_in_confirmed = getattr(staff, 'whatsapp_opt_in_confirmed', False)
    
    # Wenn Opt-In noch nicht bestätigt wurde
    if not opt_in_confirmed:
        # Wenn Opt-In-Vorlage noch nicht gesendet wurde, sende sie jetzt
        if not opt_in_sent and TWILIO_WHATSAPP_CONTENT_SID:
            log.info("📱 Sending Opt-In message to %s (waiting for confirmation)", to_phone)
            opt_in_message = "Willkommen! Du erhältst ab jetzt Benachrichtigungen über neue Aufgaben."  # Kann angepasst werden
            opt_in_result = _send_whatsapp(to_phone, opt_in_message, use_template=True)
            if opt_in_result and staff_id and db:
                # Markiere Opt-In als gesendet (aber noch nicht bestätigt)
                staff = db.get(Staff, staff_id)
                if staff:
                    staff.whatsapp_opt_in_sent = True
                    db.commit()
                    log.info("✅ Opt-In message sent to staff %d (waiting for confirmation)", staff_id)
            # KEINE normale Nachricht senden, da Opt-In noch nicht bestätigt wurde
            return opt_in_result  # True wenn Opt-In-Vorlage erfolgreich gesendet wurde
        else:
            log.info("📱 Opt-In already sent to %s, waiting for confirmation before sending normal message", to_phone)
            # KEINE normale Nachricht senden, da Opt-In noch nicht bestätigt wurde
            return False
    
    # Opt-In wurde bestätigt - sende normale Nachricht
    log.info("📱 Opt-In confirmed for %s, sending normal message", to_phone)
    return _send_whatsapp(to_phone, message, use_template=False)

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
                    log.info("📱 Sending WhatsApp to %s for staff %s (%d tasks)", phone, staff.name, len(items))
                    whatsapp_msg = build_assignment_whatsapp_message(lang, staff.name, items, base_url)
                    result = _send_whatsapp_with_opt_in(phone, whatsapp_msg, staff_id=sid, db=db)
                    if result:
                        log.info("✅ WhatsApp queued/sent to %s (staff: %s) - Delivery status will be logged via webhook", phone, staff.name)
                    else:
                        log.warning("❌ WhatsApp send failed to %s (staff: %s) - check logs above for details", phone, staff.name)
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

def send_whatsapp_for_existing_assignments():
    """Sende nur WhatsApp-Benachrichtigungen für bestehende Zuweisungen (auch wenn bereits per Email benachrichtigt)"""
    base_url = BASE_URL.rstrip("/") or ""
    with SessionLocal() as db:
        # Hole alle pending Tasks mit zugewiesenem Staff (auch wenn bereits benachrichtigt)
        pending = db.query(Task).filter(
            Task.assignment_status=="pending", 
            Task.assigned_staff_id!=None
        ).all()
        if not pending:
            return []
        staff_ids = {t.assigned_staff_id for t in pending if t.assigned_staff_id}
        report = []
        for sid in staff_ids:
            staff = db.get(Staff, sid)
            if not staff:
                continue
            # Prüfe ob Telefonnummer vorhanden ist
            phone = getattr(staff, 'phone', None) or ""
            if not phone or not phone.strip():
                log.debug("No phone number for staff %s, skipping WhatsApp", staff.name)
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
            
            # Nur WhatsApp senden (keine Email)
            try:
                log.info("📱 Sending WhatsApp to %s for staff %s (%d existing tasks)", phone, staff.name, len(items))
                whatsapp_msg = build_assignment_whatsapp_message(lang, staff.name, items, base_url)
                result = _send_whatsapp_with_opt_in(phone, whatsapp_msg, staff_id=sid, db=db)
                if result:
                    log.info("✅ WhatsApp queued/sent to %s (staff: %s) - Delivery status will be logged via webhook", phone, staff.name)
                else:
                    log.warning("❌ WhatsApp send failed to %s (staff: %s) - check logs above for details", phone, staff.name)
            except Exception as e:
                log.error("WhatsApp notification error for staff %s: %s", staff.name, e, exc_info=True)
            
            report.append({
                'staff_name': staff.name,
                'phone': phone,
                'count': len(items),
                'items': items,
            })
        db.commit()
        return report
