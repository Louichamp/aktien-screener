r"""Robuster Über-Nacht-Sync des vollen Universums (Yahoo, gratis).

Lädt das Universum (Default 1.000 Titel, --source broad), beschafft die
Yahoo-Snapshots resilient und rechnet die Pipeline cross-sectional durch.

Kernfeatures:
  * Logging nach logs/overnight_sync.log (Fortschritt in %, OK-Zahl, Fehlversuche).
  * Auto-Resume: Bereits geladene Snapshots werden als Checkpoint persistiert
    (logs/overnight_snapshots.pkl). Bricht das Netz ab, macht das Skript nach
    30 s genau bei den noch fehlenden Titeln weiter — über mehrere Pässe.
  * --spawn startet das Skript losgelöst im Hintergrund (fire-and-forget).

Hintergrund starten (Windows):
    .\.venv\Scripts\python.exe scripts\run_overnight_sync.py --spawn
Direkt (Vordergrund):
    .\.venv\Scripts\python.exe scripts\run_overnight_sync.py
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import pickle
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "overnight_sync.log"
CKPT_FILE = LOG_DIR / "overnight_snapshots.pkl"

log = logging.getLogger("overnight")


def _setup_logging(to_stdout: bool) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
    if to_stdout:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO, handlers=handlers,
        format="%(asctime)s %(levelname)-5s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass


def _chunks(seq, n):
    return [seq[i:i + n] for i in range(0, len(seq), n)]


def _load_checkpoint() -> dict:
    if CKPT_FILE.exists():
        try:
            with open(CKPT_FILE, "rb") as fh:
                data = pickle.load(fh)
            log.info("Checkpoint geladen: %d Snapshots bereits vorhanden", len(data))
            return data
        except Exception as exc:
            log.warning("Checkpoint unlesbar (%s) — starte neu", exc)
    return {}


def _save_checkpoint(cache: dict) -> None:
    tmp = CKPT_FILE.with_suffix(".tmp")
    with open(tmp, "wb") as fh:
        pickle.dump(cache, fh, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(CKPT_FILE)                          # atomar -> übersteht Crash mitten im Schreiben


async def _fetch_resumable(universe, cache, *, batch, max_passes, retry_delay) -> dict:
    from infrastructure.providers import YahooMarketDataProvider

    by_sym = {e["symbol"]: e for e in universe}
    total = len(by_sym)
    provider = YahooMarketDataProvider(
        max_concurrency=int(os.getenv("YF_MAX_CONCURRENCY", "8")))
    start = time.monotonic()
    failed_total = 0

    try:
        for p in range(1, max_passes + 1):
            missing = [s for s in by_sym if s not in cache]
            if not missing:
                break
            log.info("Pass %d/%d: %d offen, %d/%d im Cache (%.1f%%)",
                     p, max_passes, len(missing), len(cache), total, 100 * len(cache) / total)
            for chunk in _chunks(missing, batch):
                try:
                    results = await asyncio.gather(*(provider.fetch(s) for s in chunk))
                except Exception as exc:            # netzweiter Abbruch -> Auto-Resume
                    log.warning("Netzwerkabbruch (%s) — Auto-Resume in %ds", exc, retry_delay)
                    await asyncio.sleep(retry_delay)
                    continue
                got = 0
                for sym, snap in zip(chunk, results):
                    if snap is not None:
                        e = by_sym[sym]
                        if not snap.name:
                            snap.name = e.get("name")
                        if not snap.sector:
                            snap.sector = e.get("sector")
                        cache[sym] = snap
                        got += 1
                failed_total += len(chunk) - got
                _save_checkpoint(cache)
                pct = 100 * len(cache) / total
                log.info("  %.1f%% — %d/%d OK, %d offen, %d Fehlversuche, %.0fs",
                         pct, len(cache), total, total - len(cache), failed_total,
                         time.monotonic() - start)
                if got == 0:                        # ganzer Batch leer -> wohl gedrosselt
                    log.warning("  Batch komplett fehlgeschlagen (Drosselung?) — %ds Pause",
                                retry_delay)
                    await asyncio.sleep(retry_delay)
            still = total - len(cache)
            if still and p < max_passes:
                log.info("Pass %d fertig, %d offen — Retry in %ds", p, still, retry_delay)
                await asyncio.sleep(retry_delay)
    finally:
        await provider.aclose()

    log.info("Beschaffung fertig: %d/%d OK, %d Fehlversuche gesamt",
             len(cache), total, failed_total)
    return cache


async def _compute_and_write(cache: dict) -> None:
    from infrastructure.database.config import (create_engine, create_session_factory,
                                                init_models)
    from infrastructure.database.repository import ScreenerRepository
    from screener.pipeline import run_screener_pipeline

    log.info("Pipeline rechnen (cross-sectional über %d Snapshots) …", len(cache))
    engine = create_engine()
    await init_models(engine)
    sm = create_session_factory(engine)
    repo = ScreenerRepository(engine)
    async with sm() as session:
        res = await run_screener_pipeline(list(cache), session, repository=repo,
                                          snapshots=cache, commit=True)
    await engine.dispose()
    log.info("FERTIG: %d Zeilen geschrieben, %d Fehler -> %s",
             res.processed, res.failed, os.getenv("DATABASE_URL"))


async def _run(args) -> None:
    from infrastructure.providers import build_universe

    log.info("=== Overnight-Sync Start: limit=%d source=%s batch=%d ===",
             args.limit, args.source, args.batch)
    if not os.getenv("DATABASE_URL"):
        log.warning("DATABASE_URL nicht gesetzt — nutze Default aus config.py")
    universe = await build_universe(args.limit, source=args.source)
    log.info("Universe: %d Titel", len(universe))

    cache = _load_checkpoint() if args.resume else {}
    cache = await _fetch_resumable(universe, cache, batch=args.batch,
                                   max_passes=args.max_passes, retry_delay=args.retry_delay)
    if not cache:
        log.error("Keine Snapshots beschafft — Abbruch.")
        return

    if not args.no_forecast:
        from infrastructure.forecast import apply_forecasts, build_forecaster
        log.info("Forecast-Band rechnen (backend=%s) …", args.forecast_backend)
        forecaster = build_forecaster(args.forecast_backend)
        n = await apply_forecasts(forecaster, cache, horizon=args.horizon)
        await forecaster.aclose()
        log.info("Forecasts gerechnet: %d", n)

    await _compute_and_write(cache)
    if args.clear_checkpoint and CKPT_FILE.exists():
        CKPT_FILE.unlink()
        log.info("Checkpoint gelöscht.")
    log.info("=== Overnight-Sync Ende ===")


def _spawn_detached(argv: list[str]) -> None:
    """Startet dieses Skript losgelöst im Hintergrund; Ausgabe geht ins Log."""
    LOG_DIR.mkdir(exist_ok=True)
    cmd = [sys.executable, str(Path(__file__).resolve()), *argv]
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = (subprocess.DETACHED_PROCESS
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs["start_new_session"] = True
    with open(LOG_FILE, "a", encoding="utf-8") as fh:
        proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, cwd=str(ROOT), **kwargs)
    print(f"Hintergrund-Sync gestartet (PID {proc.pid}).")
    print(f"Live verfolgen:  Get-Content -Wait -Tail 20 {LOG_FILE}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5000)     # Mega-Universum
    ap.add_argument("--source", choices=["sp500", "broad"], default="broad")
    ap.add_argument("--batch", type=int, default=50)
    ap.add_argument("--max-passes", type=int, default=8)
    ap.add_argument("--retry-delay", type=int, default=30)     # Sekunden bis Auto-Resume
    ap.add_argument("--no-resume", dest="resume", action="store_false")
    ap.add_argument("--no-forecast", action="store_true", help="Forecast-Band überspringen")
    ap.add_argument("--forecast-backend", default="statistical",
                    help="statistical (gratis) oder kronos (torch)")
    ap.add_argument("--horizon", type=int, default=30)
    ap.add_argument("--clear-checkpoint", action="store_true")
    ap.add_argument("--spawn", action="store_true", help="losgelöst im Hintergrund starten")
    args = ap.parse_args()

    _load_env()
    if args.spawn:
        # eigenen Befehl ohne --spawn rekonstruieren und detached neu starten
        child = [a for a in sys.argv[1:] if a != "--spawn"]
        _spawn_detached(child)
        return

    _setup_logging(to_stdout=True)
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        log.warning("Abbruch durch Nutzer — Checkpoint bleibt erhalten (Resume möglich).")


if __name__ == "__main__":
    main()
