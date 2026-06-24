"""Beschafft das echte Universum GRATIS über Yahoo Finance und rechnet die
komplette Pipeline EINMAL durch (ohne Redis/Worker, ohne API-Key).

  DATABASE_URL=sqlite+aiosqlite:///./dev.db \
      python scripts/run_yahoo_universe.py --limit 1000 --source broad

Ablauf: Universe (S&P 500 + NASDAQ/NYSE) -> je Ticker Yahoo-Snapshot
(OHLCV + Fundamentaldaten) -> ScoreEngine/Zonen/Status/Strategien
(cross-sectional über die volle Kohorte) -> Write-Back in die DB.

Hinweise:
  * Mit Fundamentaldaten (Default) ist es gründlicher, aber langsamer (~1 HTTP/Titel).
    Für sehr große Universen `--no-fundamentals` (nur Technik, sehr schnell via Bulk).
  * Kronos-Forecast läuft hier nicht (kein torch) -> forecast_history bleibt leer;
    der forecast-Worker kann das später nachziehen.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.database.config import (create_engine, create_session_factory,
                                            init_models)
from infrastructure.database.repository import ScreenerRepository
from infrastructure.providers import YahooMarketDataProvider, build_universe
from screener.pipeline import run_screener_pipeline


def _chunks(seq, n):
    return [seq[i:i + n] for i in range(0, len(seq), n)]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--source", choices=["sp500", "broad"], default="broad")
    ap.add_argument("--period", default="2y")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--no-fundamentals", action="store_true",
                    help="nur OHLCV/Technik (schnell), keine .info-Calls")
    ap.add_argument("--no-forecast", action="store_true", help="Forecast-Band überspringen")
    ap.add_argument("--forecast-backend", default="statistical",
                    help="statistical (gratis) oder kronos (torch)")
    ap.add_argument("--horizon", type=int, default=30)
    args = ap.parse_args()

    t0 = time.monotonic()
    print(f"[1/5] Universe laden (limit={args.limit}, source={args.source}) …", flush=True)
    universe = await build_universe(args.limit, source=args.source)
    by_sym = {e["symbol"]: e for e in universe}
    syms = list(by_sym)
    print(f"      {len(syms)} Ticker.", flush=True)

    provider = YahooMarketDataProvider(period=args.period, max_concurrency=args.concurrency,
                                       with_fundamentals=not args.no_fundamentals)
    print(f"[2/5] Marktdaten von Yahoo beschaffen "
          f"({'mit' if not args.no_fundamentals else 'ohne'} Fundamentaldaten) …", flush=True)
    snaps: dict[str, object] = {}
    done = 0
    for chunk in _chunks(syms, args.batch):
        parts = await asyncio.gather(*(provider.fetch(s) for s in chunk))
        for sym, snap in zip(chunk, parts):
            if snap is None:
                continue
            e = by_sym[sym]
            if not snap.name:
                snap.name = e.get("name")
            if not snap.sector:
                snap.sector = e.get("sector")
            snaps[sym] = snap
        done += len(chunk)
        print(f"      {done}/{len(syms)} verarbeitet, {len(snaps)} Snapshots", flush=True)
    await provider.aclose()

    if not snaps:
        print("Keine Snapshots beschafft (Netzwerk?). Abbruch.", file=sys.stderr)
        raise SystemExit(1)

    if not args.no_forecast:
        from infrastructure.forecast import apply_forecasts, build_forecaster
        print(f"[3/5] Forecast-Band rechnen (backend={args.forecast_backend}) …", flush=True)
        forecaster = build_forecaster(args.forecast_backend)
        n = await apply_forecasts(forecaster, snaps, horizon=args.horizon)
        await forecaster.aclose()
        print(f"      {n} Forecasts gerechnet.", flush=True)

    print(f"[4/5] Pipeline rechnen (cross-sectional über {len(snaps)} Titel) …", flush=True)
    engine = create_engine()
    await init_models(engine)
    sm = create_session_factory(engine)
    repo = ScreenerRepository(engine)
    async with sm() as session:
        res = await run_screener_pipeline(list(snaps), session, repository=repo,
                                          snapshots=snaps, commit=True)
    await engine.dispose()

    dt = time.monotonic() - t0
    print(f"[5/5] Fertig: {res.processed} geschrieben, {res.failed} Fehler, "
          f"{len(snaps)} Snapshots in {dt:.0f}s -> {os.getenv('DATABASE_URL')}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
