"""Rotierender Voll-Universum-Sync: immer so viel wie geht, älteste zuerst.

Idee: Ein persistenter Snapshot-Cache (Pickle) wächst über die Läufe. Jeder Lauf
frischt die ÄLTESTEN N Werte neu auf (Yahoo), behält den Rest und rechnet das
GESAMTE angesammelte Universum cross-sectional neu durch -> es wird immer alles
angezeigt, was je beschafft wurde, mit `data_as_of` je Wert.

  # automatisch (CI): die ältesten ~1500 pro Lauf auffrischen
  python scripts/rotating_sync.py --cache .cache/snapshots.pkl --refresh 1500 \
      --limit 5000 --source broad

  # lokal "alles durchballern":
  python scripts/rotating_sync.py --cache .cache/snapshots.pkl --refresh all \
      --limit 5000 --source broad
  python scripts/build_site.py --deploy

Bricht NIE mit leerem Ergebnis ab: ist der Cache nach dem Lauf leer (z. B. erster
Lauf komplett gedrosselt), endet das Skript mit Exit-Code 1 -> der Deploy-Schritt
wird übersprungen und die zuletzt veröffentlichte Seite bleibt online.
"""
from __future__ import annotations

import argparse
import asyncio
import os
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
    """Beschafft `batch` resilient in Chunks (Fortschritt alle ~chunk_size Stocks).

    Chunks geben dem CI-Log Feedback und vermeiden, dass ein einzelner großer
    asyncio.gather-Aufruf viel Speicher auf einmal bindet.
    """
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
    ap.add_argument("--forecast-backend", default="statistical")
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
              f"Noch {missing // n + 1} Laeufe bis vollstaendige Abdeckung.", flush=True)
    print(f"Auffrischen: {len(batch)} Werte ({'alle' if refresh_all else 'älteste zuerst'})",
          flush=True)

    provider = build_market_data_provider("yahoo")
    fresh = await _fetch_batch(provider, batch, by_sym, passes=args.passes,
                               chunk_size=args.chunk)
    if hasattr(provider, "aclose"):
        await provider.aclose()

    cache.update(fresh)
    # Auf das aktuelle Universum begrenzen (Delistings raus, Wachstum bremsen) —
    # ABER nur, wenn die Universe-Quelle plausibel ist. Kam sie verdächtig klein
    # zurück (Fallback-Liste wegen Netzfehler), NICHT beschneiden, sonst würde der
    # mühsam angesammelte Cache zerstört ("plötzlich fast nichts").
    if len(universe_set) >= max(100, len(cache) // 2):
        cache = {t: s for t, s in cache.items() if t in universe_set}
    elif cache:
        print(f"Universe verdächtig klein ({len(universe_set)}) — Cache NICHT "
              f"beschnitten, {len(cache)} Werte behalten.", flush=True)

    if not cache:
        print("Cache leer (alles gedrosselt?) — KEIN Deploy, alte Seite bleibt online.",
              file=sys.stderr, flush=True)
        raise SystemExit(1)

    print(f"Forecast-Band für {len(cache)} Werte rechnen (backend={args.forecast_backend}) …",
          flush=True)
    forecaster = build_forecaster(args.forecast_backend)
    await apply_forecasts(forecaster, cache, horizon=args.horizon)
    if hasattr(forecaster, "aclose"):
        await forecaster.aclose()

    print(f"Pipeline über {len(cache)} Werte rechnen (cross-sectional) …", flush=True)
    engine = create_engine()
    await init_models(engine)
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
    print(f"FERTIG: {res.processed} geschrieben ({len(fresh)} neu beschafft), "
          f"Stand ältester {oldest} … neuester {newest}, {time.monotonic() - t0:.0f}s",
          flush=True)


if __name__ == "__main__":
    asyncio.run(main())
