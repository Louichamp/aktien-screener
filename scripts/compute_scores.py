"""Batch-Score-Berechnung für die Live-API-Architektur (Render + Timescale Cloud).

Läuft EINMAL pro Aufruf (GitHub Actions Cron, nicht dauerhaft) und schreibt alle
Scores direkt in die produktive Postgres/Timescale-DB (`DATABASE_URL`). Das
FastAPI-Backend (`api/main.py`) liest diese Tabelle danach nur noch — es
berechnet nichts mehr live bei Requests.

Rollierender Cache (wie `rotating_sync.py` für den Netlify-Pfad): ein
Snapshot-Cache (Pickle) wächst über die Läufe, jeder Lauf frischt nur die
ÄLTESTEN N Ticker neu auf, rechnet aber das GESAMTE angesammelte Universum
cross-sectional neu (Peer-Perzentile brauchen die volle Kohorte, nicht nur den
Tages-Batch). Der Cache liegt bewusst NICHT in der DB — nur das fertige,
kompakte Ergebnis (`screener_rows`) landet in Postgres. Das hält den
Timescale-Storage klein (siehe Punkt 5/7 der Kostenschätzung); Rohdaten
(Kerzen, Technicals, Fundamentals) sind Wegwerf-Zwischenstand, kein Produktdatum.

Kronos/torch bewusst NICHT hier: der GitHub-Actions-Free-Runner hat keine GPU,
torch+transformers ist >2GB und würde den Free-Minuten-Etat sprengen. Es läuft
das torch-freie `StatisticalForecaster` (GBM aus echten Log-Renditen) — exakt
dieselbe Wahl wie im bereits produktiven Netlify-Pfad.

Eigenständiges Skript (keine Abhängigkeit von rotating_sync.py/build_site.py):
die beiden Pfade (Netlify-Static vs. Live-API) haben unterschiedliche
Nach-Schritte (Frontend-Export vs. nichts — Vercel baut selbst) und sollen sich
nicht gegenseitig destabilisieren können. Etwas Logik-Überlappung mit
rotating_sync.py ist der bewusste Preis dafür.

  # täglicher Cron-Lauf (GitHub Actions): die ältesten ~1500 auffrischen
  python scripts/compute_scores.py --cache .cache/snapshots.pkl --refresh 1500 \
      --limit 5250 --source broad

  # lokal: kompletten Rebuild erzwingen
  python scripts/compute_scores.py --cache .cache/snapshots.pkl --refresh all
"""
from __future__ import annotations

import argparse
import asyncio
import pickle
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from infrastructure.database.config import (create_engine, create_session_factory,
                                            init_models)
from infrastructure.database.repository import ScreenerRepository
from infrastructure.forecast import apply_forecasts, build_forecaster
from infrastructure.providers import build_market_data_provider, build_universe
from screener.pipeline import run_screener_pipeline


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_cache(path: Path) -> dict:
    if path.exists():
        try:
            with open(path, "rb") as fh:
                data = pickle.load(fh)
            print(f"Cache geladen: {len(data)} Snapshots", flush=True)
            return data
        except Exception as exc:
            print(f"Cache unlesbar ({exc}) — starte leer", flush=True)
    return {}


def _save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as fh:
        pickle.dump(cache, fh, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)


def _select_oldest(universe_tickers: list[str], cache: dict, n: int) -> list[str]:
    """Nie beschaffte zuerst, dann nach data_as_of aufsteigend (älteste zuerst)."""
    def key(t: str):
        snap = cache.get(t)
        return getattr(snap, "as_of", None) or ""        # "" = nie -> ganz vorne
    return sorted(universe_tickers, key=key)[:n]


async def _fetch_batch(provider, batch: list[str], by_sym: dict,
                       *, passes: int, chunk_size: int = 200) -> dict:
    """Beschafft `batch` resilient in Chunks (Fortschritt alle ~chunk_size Stocks)."""
    got: dict = {}
    todo = list(batch)
    for p in range(1, passes + 1):
        if not todo:
            break
        failed: list[str] = []
        done_this_pass = 0
        for i in range(0, len(todo), chunk_size):
            chunk = todo[i: i + chunk_size]
            results = await asyncio.gather(*(provider.fetch(t) for t in chunk),
                                           return_exceptions=True)
            for sym, snap in zip(chunk, results):
                if snap is None or isinstance(snap, Exception):
                    failed.append(sym)
                    continue
                e = by_sym.get(sym, {})
                if not snap.name:
                    snap.name = e.get("name")
                if not snap.sector:
                    snap.sector = e.get("sector")
                snap.as_of = _now_iso()
                got[sym] = snap
                done_this_pass += 1
            pct = (i + len(chunk)) / len(todo) * 100
            print(f"  Pass {p}/{passes}: {i + len(chunk)}/{len(todo)} verarbeitet "
                  f"({pct:.0f}%) — {done_this_pass} ok, {len(failed)} offen", flush=True)
        todo = failed
        if todo and p < passes:
            print(f"  Pause 20s vor Retry-Pass {p + 1} ({len(todo)} offen) …", flush=True)
            await asyncio.sleep(20)
    return got


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(ROOT / ".cache" / "snapshots.pkl"))
    ap.add_argument("--refresh", default="1500", help="Anzahl ältester Werte oder 'all'")
    ap.add_argument("--limit", type=int, default=5250)
    ap.add_argument("--source", choices=["sp500", "broad"], default="broad")
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--chunk", type=int, default=200, help="Fetch-Chunk-Größe für Progress-Logging")
    # Bewusst fix "statistical" (torch-frei) — s. Modul-Docstring. Kein --forecast-backend
    # Flag, damit niemand aus Versehen echtes Kronos/torch im Free-Runner aktiviert.
    ap.add_argument("--horizon", type=int, default=30)
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")               # override=False -> Shell-Env gewinnt
    except Exception:
        pass

    t0 = time.monotonic()
    cache_path = Path(args.cache)
    cache = _load_cache(cache_path)

    print(f"Universe laden (limit={args.limit}, source={args.source}) …", flush=True)
    universe = await build_universe(args.limit, source=args.source)
    by_sym = {e["symbol"]: e for e in universe}
    universe_tickers = list(by_sym)
    universe_set = set(universe_tickers)

    refresh_all = str(args.refresh).lower() == "all"
    n = len(universe_tickers) if refresh_all else max(0, int(args.refresh))
    batch = _select_oldest(universe_tickers, cache, n)

    cached_total = len(cache)
    missing = len([t for t in universe_tickers if t not in cache])
    print(f"Cache: {cached_total} vorhanden, {missing} noch nie beschafft, "
          f"{len(universe_tickers)} im Universum", flush=True)
    if missing > 0 and not refresh_all:
        print(f"  Bootstrap-Hinweis: {missing} Stocks noch nie gesehen. "
              f"Noch {missing // max(n, 1) + 1} Läufe bis vollständige Abdeckung.", flush=True)
    print(f"Auffrischen: {len(batch)} Werte ({'alle' if refresh_all else 'älteste zuerst'})",
          flush=True)

    provider = build_market_data_provider("yahoo")
    fresh = await _fetch_batch(provider, batch, by_sym, passes=args.passes,
                               chunk_size=args.chunk)
    if hasattr(provider, "aclose"):
        await provider.aclose()

    cache.update(fresh)
    if len(universe_set) >= max(100, len(cache) // 2):
        cache = {t: s for t, s in cache.items() if t in universe_set}
    elif cache:
        print(f"Universe verdächtig klein ({len(universe_set)}) — Cache NICHT "
              f"beschnitten, {len(cache)} Werte behalten.", flush=True)

    if not cache:
        print("Cache leer (alles gedrosselt?) — DB bleibt unverändert.",
              file=sys.stderr, flush=True)
        raise SystemExit(1)

    print(f"Forecast-Band für {len(cache)} Werte rechnen (statistical, torch-frei) …",
          flush=True)
    forecaster = build_forecaster("statistical")
    await apply_forecasts(forecaster, cache, horizon=args.horizon)
    if hasattr(forecaster, "aclose"):
        await forecaster.aclose()

    print(f"Pipeline über {len(cache)} Werte rechnen (cross-sectional) …", flush=True)
    engine = create_engine()                       # DATABASE_URL -> Timescale Cloud Postgres
    await init_models(engine)                       # idempotent; Produktions-Schema via Alembic
    sm = create_session_factory(engine)
    repo = ScreenerRepository(engine)
    async with sm() as session:
        res = await run_screener_pipeline(list(cache), session, repository=repo,
                                          snapshots=cache, commit=True)
    await engine.dispose()

    _save_cache(cache_path, cache)

    stamps = [getattr(s, "as_of", None) for s in cache.values() if getattr(s, "as_of", None)]
    oldest = min(stamps) if stamps else "—"
    newest = max(stamps) if stamps else "—"
    print(f"FERTIG: {res.processed} in DB geschrieben ({len(fresh)} neu beschafft), "
          f"Stand ältester {oldest} … neuester {newest}, {time.monotonic() - t0:.0f}s",
          flush=True)


if __name__ == "__main__":
    asyncio.run(main())
