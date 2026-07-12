"""Vercel Python Serverless Function — dünner Shim für die echte FastAPI-App.

Vercels Python-Runtime erwartet eine ASGI-`app`-Variable in `<root>/api/*.py`
relativ zum Projekt-Root (hier: `frontend/`, Vercels "Root Directory"). Die
eigentliche FastAPI-App lebt bewusst NICHT hier, sondern im Repo-Root-Paket
`api/` (geteilt mit Tests, Alembic-env.py, lokalem `uvicorn api.main:app` für
Self-Hosting/Render als Alternative) — dieser Shim hängt den Repo-Root an
`sys.path` und importiert sie unverändert. Keine Logik-Duplikation.

Routing: `vercel.json` leitet `/api/*` per Rewrite hierher; FastAPIs eigener
Router (`api/routes.py`, prefix `/api/v1`) übernimmt danach intern.
"""
from __future__ import annotations

import sys
from pathlib import Path

# frontend/api/index.py -> frontend/api -> frontend -> <repo-root>
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from api.main import create_app  # noqa: E402

app = create_app()
