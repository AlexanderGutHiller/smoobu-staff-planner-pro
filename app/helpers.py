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
    # Importiere die Übersetzungen aus main.py (später hierher verschieben)
    from .main import get_translations as _get_translations
    return _get_translations(lang)

