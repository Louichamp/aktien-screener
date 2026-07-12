"""FastAPI-Lese-Schicht für den Screener (API v1).

Bewusst OHNE Re-Export von `create_app` hier (kein `from .main import
create_app`): das erzeugt einen zirkulären Import, sobald `api/main.py`
selbst als direkter Modul-Entry-Point geladen wird (z. B. Vercels
Python-Runtime lädt `api/main.py` per Pfad -> triggert zuerst dieses
`__init__.py` -> das importiert wiederum `.main`, das gerade erst mitten im
Laden ist -> `ImportError: cannot import name 'create_app' from partially
initialized module`, live auf Vercel reproduziert). Import stattdessen immer
explizit: `from api.main import create_app`.
"""
from __future__ import annotations
