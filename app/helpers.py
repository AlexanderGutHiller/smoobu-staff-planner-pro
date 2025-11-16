"""Helper functions used across routers"""
from fastapi import Request
from typing import Dict

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

