"""Produktiv-Starter: 3 arq-Worker + FastAPI parallel, mit .env-Umgebung.

Startet je einen Prozess für die Ingest-, Forecast- und Compute-Queue sowie
den uvicorn-Server. Lädt zuerst `.env` (python-dotenv, mit Fallback-Parser),
optional führt `--migrate` vorab `alembic upgrade head` aus.

  python scripts/start_prod.py [--migrate]

Beendet sich ein Kindprozess unerwartet, werden alle anderen sauber gestoppt
(damit kein halb-laufendes System zurückbleibt). SIGINT/SIGTERM (bzw. Ctrl-C)
fahren alle Prozesse geordnet herunter.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRACE_SECONDS = 15


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


def processes() -> list[tuple[str, list[str]]]:
    py = sys.executable
    api_host = os.getenv("API_HOST", "0.0.0.0")
    api_port = os.getenv("API_PORT", "8000")
    api_workers = os.getenv("API_WORKERS", "2")
    return [
        ("ingest",   [py, "-m", "arq", "infrastructure.worker.IngestSettings"]),
        ("forecast", [py, "-m", "arq", "infrastructure.worker.ForecastSettings"]),
        ("compute",  [py, "-m", "arq", "infrastructure.worker.ComputeSettings"]),
        ("api",      [py, "-m", "uvicorn", "api.main:app",
                      "--host", api_host, "--port", api_port, "--workers", api_workers]),
    ]


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
    if not os.getenv("FMP_API_KEY"):
        print("[start_prod] WARN: FMP_API_KEY nicht gesetzt — Ingest bleibt leer", file=sys.stderr)

    running: list[tuple[str, subprocess.Popen]] = []
    for name, cmd in processes():
        print(f"[start_prod] starte {name}: {' '.join(cmd)}", flush=True)
        running.append((name, subprocess.Popen(cmd, cwd=ROOT)))

    stopping = {"flag": False}

    def _signal(_signum, _frame):
        stopping["flag"] = True

    signal.signal(signal.SIGINT, _signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal)

    exit_code = 0
    try:
        while not stopping["flag"]:
            for name, proc in running:
                rc = proc.poll()
                if rc is not None:                  # ein Prozess ist beendet
                    print(f"[start_prod] '{name}' endete (rc={rc}) — fahre alles herunter",
                          file=sys.stderr, flush=True)
                    exit_code = rc or 1
                    stopping["flag"] = True
                    break
            time.sleep(1.0)
    except KeyboardInterrupt:
        stopping["flag"] = True

    # Geordnetes Herunterfahren
    print("[start_prod] terminiere Kindprozesse ...", flush=True)
    for _name, proc in running:
        if proc.poll() is None:
            proc.terminate()
    deadline = time.time() + GRACE_SECONDS
    for _name, proc in running:
        if proc.poll() is None:
            try:
                proc.wait(timeout=max(0.0, deadline - time.time()))
            except subprocess.TimeoutExpired:
                proc.kill()
    print("[start_prod] beendet", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
