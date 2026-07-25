"""Befüllt die Tabelle mit der ECHTEN Basis-Kohorte (S&P 500 + NASDAQ 100).

Holt über den FMPMarketDataProvider die Index-Mitglieder (Symbol, Name, Branche)
und reichert je Ticker mit einem leichten /profile-Call um Land, Währung, Preis
und Dividendenrendite an. Geschrieben werden zunächst nur die Stammdaten — die
Scores/Targets/Forecasts liefert anschließend der compute-Lauf des Workers.

  DATABASE_URL=postgresql+asyncpg://... FMP_API_KEY=... \
      python scripts/seed_real_universe.py --indices sp500 nasdaq

Die eigentliche Logik steckt in `seed_real_universe()` (provider-agnostisch und
damit testbar mit einem Fake-Provider).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.database.config import (create_engine, create_session_factory,
                                            init_models)
from infrastructure.database.repository import ScreenerRepository


async def seed_real_universe(provider: Any, repository: ScreenerRepository,
                             session_factory: Any, *,
                             indices: tuple[str, ...] = ("sp500", "nasdaq"),
                             concurrency: int = 8, limit: int | None = None) -> int:
    """Index-Konstituenten -> Profile -> Upsert der Stammdaten. Gibt #Ticker zurück.

    Re-runs aktualisieren nur die Stammdaten-Spalten (Upsert), nie die Scores.
    """
    # 1) Konstituenten einsammeln (Name/Branche kommen kostenlos mit).
    meta: dict[str, dict[str, Any]] = {}
    for idx in indices:
        for c in await provider.fetch_constituents(idx):
            sym = c.get("symbol")
            if not sym:
                continue
            m = meta.setdefault(sym, {})
            m.setdefault("name", c.get("name"))
            m.setdefault("sector", c.get("sector"))
    tickers = list(meta)
    if limit is not None:
        tickers = tickers[:limit]

    # 2) Profile parallel (Concurrency-begrenzt; FMP-Limit hält der Rate-Limiter).
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(tk: str) -> tuple[str, dict[str, Any] | None]:
        async with sem:
            try:
                return tk, await provider.fetch_profile_meta(tk)
            except Exception:
                return tk, None

    profiles = dict(await asyncio.gather(*(one(t) for t in tickers)))

    # 3) Stammdaten upserten (nur Metadaten-Spalten; JSON-NOT-NULL-Spalten füllen
    #    beim INSERT ihre Defaults []/{}). Pro Ticker in einer SAVEPOINT
    #    (begin_nested) — sonst killt EIN Constraint-Verstoß (z. B. ein Name/eine
    #    Branche/ein Land, das die jeweilige String-Spaltenbreite sprengt) die
    #    komplette Transaktion und damit den ganzen Lauf ohne einen einzigen
    #    geschriebenen Ticker (derselbe Bug wie der, der screener/pipeline.py's
    #    Write-Back drei Tage in Folge crashen ließ — hier bislang ungefixt).
    failed: list[str] = []
    async with session_factory() as s:
        for tk in tickers:
            base = meta.get(tk, {})
            prof = profiles.get(tk) or {}
            try:
                async with s.begin_nested():
                    await repository.upsert_screener_row(s, dict(
                        ticker=tk,
                        name=prof.get("name") or base.get("name") or tk,
                        sector=prof.get("sector") or base.get("sector"),
                        country=prof.get("country"),
                        asset_class=prof.get("asset_class") or "Aktie",
                        price=prof.get("price"),
                        currency=prof.get("currency") or "USD",
                        dividend_yield=prof.get("dividend_yield"),
                    ))
            except Exception as exc:                   # ein Ticker darf den Lauf nie killen
                failed.append(tk)
                print(f"  WARN: {tk} nicht geschrieben ({exc})", file=sys.stderr)
        await s.commit()
    if failed:
        print(f"seed_real_universe: {len(failed)} von {len(tickers)} Tickern "
              f"übersprungen: {', '.join(failed)}", file=sys.stderr)
    return len(tickers)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--indices", nargs="+", default=["sp500", "nasdaq"])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()

    if not os.getenv("FMP_API_KEY"):
        print("FEHLER: FMP_API_KEY nicht gesetzt — echter Seed braucht einen Key.",
              file=sys.stderr)
        raise SystemExit(2)

    from infrastructure.providers import FMPMarketDataProvider

    engine = create_engine()
    await init_models(engine)
    sm = create_session_factory(engine)
    repo = ScreenerRepository(engine)
    provider = FMPMarketDataProvider()
    try:
        n = await seed_real_universe(provider, repo, sm, indices=tuple(args.indices),
                                     concurrency=args.concurrency, limit=args.limit)
    finally:
        await provider.aclose()
        await engine.dispose()
    print(f"seeded {n} echte Instrumente ({', '.join(args.indices)}) -> {os.getenv('DATABASE_URL')}")


if __name__ == "__main__":
    asyncio.run(main())
