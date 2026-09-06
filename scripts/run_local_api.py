"""Lokaler API-Start gegen eine SQLite-Datei — zum Anschauen ohne Neon.

Die produktive Datenbank liegt bei Neon; eine TLS-Verbindung dorthin scheitert
unter Windows zuverlaessig (ProactorEventLoop/Firewall). Fuer das Pruefen von
Oberflaeche und Endpunkten reicht eine lokale Datei, die `compute_scores.py`
mit echten Marktdaten befuellen kann:

    set DATABASE_URL=sqlite+aiosqlite:///./.cache/local.db
    python scripts/compute_scores.py --cache .cache/local_snaps.pkl \
        --refresh 60 --limit 60 --source sp500
    python scripts/run_local_api.py

Danach `npm --prefix frontend run dev` mit NEXT_PUBLIC_API_BASE=http://localhost:8000
in frontend/.env.local.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_DB = f"sqlite+aiosqlite:///{(ROOT / '.cache' / 'local_preview.db').as_posix()}"


def main() -> None:
    os.environ.setdefault("DATABASE_URL", DEFAULT_DB)
    os.environ.setdefault("CORS_ORIGINS",
                          "http://localhost:3000,http://127.0.0.1:3000")
    print(f"API auf http://127.0.0.1:8000  (DB: {os.environ['DATABASE_URL']})")
    import uvicorn
    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
