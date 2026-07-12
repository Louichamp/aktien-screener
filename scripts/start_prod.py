"""Produktiv-Starter für die Lese-Schicht: nur noch uvicorn, kein Worker mehr.

Die Score-Berechnung läuft NICHT mehr als permanenter Prozess (der arq-Worker
wurde entfernt), sondern als eigenständiger Batch-Job via
`scripts/compute_scores.py` (z. B. GitHub Actions Cron, siehe
`.github/workflows/compute-scores.yml`). Dieses Skript startet nur noch die
FastAPI-Lese-Schicht — für Render (`render.yaml`) direkt per `uvicorn`-Command
ausreichend; dieses Skript bleibt für Self-Hosting (eigener Server/VPS) mit
Migration-Vorschritt nützlich.

  python scripts/start_prod.py [--migrate]
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> None:
    env_file = ROOT / ".env"
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
    except ImportError:                              # minimaler Fallback ohne python-dotenv
        if env_file.exists():
            for raw in env_file.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def run_migrations() -> None:
    print("[start_prod] alembic upgrade head ...", flush=True)
    # `python -m alembic` existiert nicht (Paket ohne __main__) -> Konsolen-Entry.
    rc = subprocess.call(
        [sys.executable, "-c", "from alembic.config import main; main()", "upgrade", "head"],
        cwd=ROOT)
    if rc != 0:
        print(f"[start_prod] Migration fehlgeschlagen (rc={rc}) — Abbruch", file=sys.stderr)
        sys.exit(rc)


def main() -> int:
    load_env()
    if "--migrate" in sys.argv:
        run_migrations()

    if not os.getenv("DATABASE_URL"):
        print("[start_prod] WARN: DATABASE_URL nicht gesetzt", file=sys.stderr)

    api_host = os.getenv("API_HOST", "0.0.0.0")
    api_port = os.getenv("API_PORT", "8000")
    api_workers = os.getenv("API_WORKERS", "2")
    cmd = [sys.executable, "-m", "uvicorn", "api.main:app",
           "--host", api_host, "--port", api_port, "--workers", api_workers]
    print(f"[start_prod] starte api: {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
