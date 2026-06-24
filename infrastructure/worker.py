"""arq-Worker mit dreistufiger Topologie.

Drei Queues (= drei Worker-Pools, jeweils eigene WorkerSettings):
  * ingest   – Datenbeschaffung (IO-bound, hohe Async-Konkurrenz)
  * forecast – dedizierte Kronos-Inferenz (Modell warm, begrenzte Slots)
  * compute  – Engines + Pipeline-Runner + transaktionaler Write-Back
               (trägt den Cron-Scheduler und den Orchestrator)

Der Orchestrator `screener_run` fächert über die Queues auf:
  ingest -> forecast -> compute. Kronos liegt isoliert im forecast-Pool,
damit seine Rechenlast die IO-/Compute-Jobs nicht blockiert.

Start in Produktion (drei Prozesse):
    arq infrastructure.worker.ComputeSettings
    arq infrastructure.worker.IngestSettings
    arq infrastructure.worker.ForecastSettings
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from infrastructure.database import (ScreenerRepository, create_engine,
                                     create_session_factory)
from screener.pipeline import MarketSnapshot, run_screener_pipeline

log = logging.getLogger("screener.worker")

QUEUE_INGEST = "screener:ingest"
QUEUE_FORECAST = "screener:forecast"
QUEUE_COMPUTE = "screener:compute"

REDIS_SETTINGS = RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://localhost:6379"))
WATCHLIST = [t for t in os.getenv("WATCHLIST", "").split(",") if t]

# Kronos-Resilienz (tunbar über Umgebungsvariablen):
FORECAST_HORIZON = int(os.getenv("FORECAST_HORIZON", "30"))     # Inferenz-Tage
FORECAST_ATTEMPTS = int(os.getenv("FORECAST_ATTEMPTS", "3"))    # Versuche je Instrument
FORECAST_TIMEOUT = float(os.getenv("FORECAST_TIMEOUT", "45"))   # Sekunden je Inferenz
FORECAST_BACKOFF = float(os.getenv("FORECAST_BACKOFF", "1.5"))  # Basis für Exponential-Backoff

# Batch-Orchestrierung: Ingest/Forecast laufen in Sub-Task-Gruppen à BATCH_SIZE.
SCREENER_BATCH_SIZE = int(os.getenv("SCREENER_BATCH_SIZE", "50"))
INGEST_JOB_TIMEOUT = int(os.getenv("INGEST_JOB_TIMEOUT", "300"))
FORECAST_JOB_TIMEOUT = int(os.getenv("FORECAST_JOB_TIMEOUT", "1200"))
COMPUTE_JOB_TIMEOUT = int(os.getenv("COMPUTE_JOB_TIMEOUT", "1800"))
ORCHESTRATOR_TIMEOUT = int(os.getenv("ORCHESTRATOR_TIMEOUT", "3600"))

# Fehlerklassen, bei denen ein Retry sinnvoll ist (Netzwerk-Timeout, GPU-Verzögerung).
_RETRYABLE = (asyncio.TimeoutError, TimeoutError, ConnectionError, OSError)


def batched(seq: list[Any], n: int) -> list[list[Any]]:
    """Teilt eine Liste in Batches der Größe `n` (letzter Batch ggf. kleiner)."""
    n = max(1, n)
    return [seq[i:i + n] for i in range(0, len(seq), n)]


# --------------------------------------------------------------------------- #
#  Integrationspunkte: echte Implementierungen mit robustem Fallback
# --------------------------------------------------------------------------- #
class _UnconfiguredProvider:
    """Fallback ohne FMP_API_KEY — liefert keine Daten (Lauf bleibt leer)."""
    async def fetch(self, ticker: str) -> MarketSnapshot | None:
        log.error("Kein FMP_API_KEY gesetzt — %s wird übersprungen", ticker)
        return None


class _UnavailableKronos:
    """Fallback, wenn Kronos/torch nicht ladbar ist — Forecast degradiert sauber."""
    async def forecast(self, snap: MarketSnapshot, *, horizon: int) -> dict[str, Any]:
        raise RuntimeError("Kronos-Modell nicht geladen (siehe startup_forecast-Log)")


def _build_provider() -> Any:
    """Markt-Provider aus DATA_PROVIDER (Default: Yahoo, gratis).

    `fmp` braucht FMP_API_KEY; fehlt er, läuft der Provider im Leerlauf.
    """
    name = os.getenv("DATA_PROVIDER", "yahoo").lower()
    if name == "fmp" and not os.getenv("FMP_API_KEY"):
        log.warning("DATA_PROVIDER=fmp, aber FMP_API_KEY fehlt — Provider im Leerlauf")
        return _UnconfiguredProvider()
    from infrastructure.providers import build_market_data_provider
    log.info("Markt-Provider aktiv: %s", name)
    return build_market_data_provider(name)


def _build_kronos() -> Any:
    """Kronos-Modell warm laden; bei Fehler (kein torch/Modell) sauber degradieren."""
    try:
        from infrastructure.forecast import KronosForecaster
        model = KronosForecaster()
        log.info("forecast-worker: Kronos-Modell warm geladen")
        return model
    except Exception as exc:                       # torch fehlt, Modell nicht erreichbar, ...
        log.error("Kronos konnte nicht geladen werden (%s) — Forecast degradiert", exc)
        return _UnavailableKronos()


# --------------------------------------------------------------------------- #
#  Lifecycle
# --------------------------------------------------------------------------- #
async def startup(ctx: dict[str, Any]) -> None:
    """asyncpg-Pool (Engine) + Session-Factory + Repository + Provider."""
    engine = create_engine()
    ctx["engine"] = engine
    ctx["session_factory"] = create_session_factory(engine)
    ctx["repository"] = ScreenerRepository(engine)
    ctx["provider"] = _build_provider()
    ctx["shutting_down"] = False
    log.info("worker startup: PostgreSQL-Pool + Redis bereit")


async def startup_forecast(ctx: dict[str, Any]) -> None:
    """Wie startup, lädt zusätzlich das Kronos-Modell einmalig (warm)."""
    await startup(ctx)
    ctx["kronos"] = _build_kronos()


async def shutdown(ctx: dict[str, Any]) -> None:
    """Graceful Shutdown: keine neuen Jobs, laufende Transaktion zu Ende, Pool schließen."""
    ctx["shutting_down"] = True
    provider = ctx.get("provider")
    if provider is not None and hasattr(provider, "aclose"):
        await provider.aclose()                    # FMP-HTTP-Client schließen
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()
    log.info("worker shutdown: Pools sauber geschlossen")


# --------------------------------------------------------------------------- #
#  Tasks
# --------------------------------------------------------------------------- #
async def ingest_snapshots(ctx: dict[str, Any], tickers: list[str]) -> dict[str, MarketSnapshot]:
    """ingest-Queue: Markt-/Stammdaten beschaffen (pro Ticker fehlerisoliert)."""
    provider = ctx["provider"]
    out: dict[str, MarketSnapshot] = {}
    failed = 0
    for tk in tickers:
        try:
            snap = await provider.fetch(tk)
        except Exception as exc:                   # ein Ticker darf den Lauf nicht killen
            log.warning("ingest %s fehlgeschlagen: %s", tk, exc)
            failed += 1
            continue
        if snap is not None:
            out[tk] = snap
    log.info("ingest: %d/%d Snapshots beschafft (%d Fehler)", len(out), len(tickers), failed)
    return out


async def _forecast_with_retries(kronos: Any, snap: MarketSnapshot) -> dict[str, Any]:
    """Eine Kronos-Inferenz mit Timeout + Exponential-Backoff-Retry.

    Jeder Versuch ist hart per `wait_for` gedeckelt (hängende GPU/Netz blockiert
    nicht ewig). Nach `FORECAST_ATTEMPTS` erfolglosen Versuchen wird die letzte
    Exception propagiert; der Aufrufer entscheidet über den Umgang.
    """
    last: Exception | None = None
    for attempt in range(1, FORECAST_ATTEMPTS + 1):
        try:
            return await asyncio.wait_for(
                kronos.forecast(snap, horizon=FORECAST_HORIZON), timeout=FORECAST_TIMEOUT)
        except _RETRYABLE as exc:
            last = exc
            if attempt < FORECAST_ATTEMPTS:
                delay = FORECAST_BACKOFF ** attempt
                log.warning("forecast %s: Versuch %d/%d fehlgeschlagen (%s), Retry in %.1fs",
                            snap.ticker, attempt, FORECAST_ATTEMPTS, exc, delay)
                await asyncio.sleep(delay)
    raise last if last is not None else RuntimeError("forecast: unbekannter Fehler")


async def forecast_snapshots(ctx: dict[str, Any],
                             snaps: dict[str, MarketSnapshot]) -> dict[str, MarketSnapshot]:
    """forecast-Queue: Kronos-Prognose je Instrument (warmes Modell).

    Resilienz: Inferenz je Instrument mit Retry/Timeout. Ein dauerhaft fallender
    Forecast setzt `snap.forecast = None` (die Pipeline läuft ohne Kronos weiter)
    statt die ingest/compute-Kette zu blockieren — ein Kronos-Schluckauf darf den
    Gesamtlauf nie aufhalten.
    """
    kronos = ctx["kronos"]
    ok = failed = 0
    for snap in snaps.values():
        try:
            snap.forecast = await _forecast_with_retries(kronos, snap)
            ok += 1
        except Exception as exc:                # nach allen Retries: degradieren
            log.error("forecast %s: endgültig fehlgeschlagen, ohne Kronos fortfahren: %s",
                      snap.ticker, exc)
            snap.forecast = None
            failed += 1
    log.info("forecast: %d ok, %d degradiert (von %d)", ok, failed, len(snaps))
    return snaps


async def compute_and_persist(ctx: dict[str, Any],
                              snaps: dict[str, MarketSnapshot]) -> dict[str, int]:
    """compute-Queue: Engines + Pipeline + transaktionaler Write-Back.

    Der gesamte Write-Back läuft in EINER Transaktion mit genau einem commit.
    Bricht der Job ab (z. B. SIGTERM, Fehler), schließt der Session-Context
    ohne commit -> Rollback -> StatusMemory bleibt konsistent.
    """
    session_factory = ctx["session_factory"]
    repository = ctx["repository"]
    async with session_factory() as session:
        res = await run_screener_pipeline(
            list(snaps), session, repository=repository, snapshots=snaps, commit=True)
    log.info("compute: %d verarbeitet, %d Fehler", res.processed, res.failed)
    return {"processed": res.processed, "failed": res.failed}


async def screener_run(ctx: dict[str, Any], tickers: list[str] | None = None) -> dict[str, int]:
    """Orchestrator (compute-Queue, auch vom Cron getriggert).

    Fächert in Batches über die drei Queues auf:
      * INGEST   – ein Sub-Job je Batch (à SCREENER_BATCH_SIZE), parallel; der
                   im Worker-Prozess GETEILTE Provider-Rate-Limiter drosselt alle
                   gleichzeitigen FMP-Calls global -> nahtlos, ohne 429.
      * FORECAST – ebenfalls batchweise (Pool max_jobs=2 -> sanft serialisiert).
      * COMPUTE  – BEWUSST ein einziger Job über das gesamte Universum: die
                   Score-Engine (Peer-Perzentile) und das Strategie-Ranking sind
                   cross-sectional und brauchen die volle Kohorte auf einmal.
    """
    tickers = tickers or WATCHLIST
    if not tickers:
        log.warning("screener_run: leere Watchlist")
        return {"processed": 0, "failed": 0}
    redis = ctx["redis"]

    ticker_batches = batched(tickers, SCREENER_BATCH_SIZE)
    log.info("screener_run: %d Ticker in %d Batches à %d",
             len(tickers), len(ticker_batches), SCREENER_BATCH_SIZE)

    # 1) INGEST – ein Job pro Batch, Ergebnisse zusammenführen.
    ingest_jobs = [await redis.enqueue_job("ingest_snapshots", b, _queue_name=QUEUE_INGEST)
                   for b in ticker_batches]
    snaps: dict[str, MarketSnapshot] = {}
    for part in await asyncio.gather(*(j.result(timeout=INGEST_JOB_TIMEOUT) for j in ingest_jobs)):
        snaps.update(part)
    log.info("screener_run: %d Snapshots beschafft", len(snaps))
    if not snaps:
        return {"processed": 0, "failed": 0}

    # 2) FORECAST – batchweise; Snapshots wieder zusammenführen.
    snap_items = list(snaps.items())
    fc_jobs = [await redis.enqueue_job("forecast_snapshots", dict(chunk), _queue_name=QUEUE_FORECAST)
               for chunk in batched(snap_items, SCREENER_BATCH_SIZE)]
    snaps = {}
    for part in await asyncio.gather(*(j.result(timeout=FORECAST_JOB_TIMEOUT) for j in fc_jobs)):
        snaps.update(part)

    # 3) COMPUTE – ein universumsweiter Job (cross-sectional, s.o.).
    j_compute = await redis.enqueue_job("compute_and_persist", snaps, _queue_name=QUEUE_COMPUTE)
    return await j_compute.result(timeout=COMPUTE_JOB_TIMEOUT)


# --------------------------------------------------------------------------- #
#  WorkerSettings je Queue
# --------------------------------------------------------------------------- #
class IngestSettings:
    queue_name = QUEUE_INGEST
    functions = [ingest_snapshots]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = REDIS_SETTINGS
    max_jobs = 50                      # IO-bound -> hohe Async-Konkurrenz
    job_timeout = INGEST_JOB_TIMEOUT


class ForecastSettings:
    queue_name = QUEUE_FORECAST
    functions = [forecast_snapshots]
    on_startup = startup_forecast      # lädt Kronos einmalig (warm)
    on_shutdown = shutdown
    redis_settings = REDIS_SETTINGS
    max_jobs = 2                       # begrenzte GPU/CPU-Slots
    job_timeout = FORECAST_JOB_TIMEOUT


class ComputeSettings:
    queue_name = QUEUE_COMPUTE
    functions = [compute_and_persist, screener_run]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = REDIS_SETTINGS
    max_jobs = 4
    # deckt den Orchestrator (wartet auf alle Sub-Jobs) UND compute_and_persist ab.
    job_timeout = ORCHESTRATOR_TIMEOUT
    # Täglicher Lauf nach Börsenschluss + initialer Lauf beim Start.
    # Für festes Intervall stattdessen z. B. minute=set(range(0, 60, 15)).
    cron_jobs = [cron(screener_run, hour={22}, minute={0}, run_at_startup=True)]
