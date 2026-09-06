"""Erzeugt die Wochen-Watchlist aus den bereits berechneten Screener-Zeilen.

Läuft montags kurz nach dem täglichen Score-Lauf. Es wird nichts neu
gerechnet und nichts von außen geholt — die Watchlist ist eine Auswahl und
Ordnung dessen, was ohnehin in der Datenbank steht. Das hält den Lauf unter
einer Sekunde und macht ihn beliebig wiederholbar.

    python scripts/build_watchlist.py                 # schreibt in die DB
    python scripts/build_watchlist.py --dry-run       # nur anzeigen
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from infrastructure.database.config import create_engine, create_session_factory
from infrastructure.database.models import ScreenerRowModel, WeeklyWatchlistModel
from screener.watchlist import build_watchlist

# Wie viele Ausgaben aufgehoben werden. Der Verlauf ist nützlich, soll aber
# nicht unbegrenzt wachsen — ein Jahr reicht für jeden Rückblick.
KEEP_HISTORY = 52


def _week_label(now: datetime) -> str:
    iso = now.isocalendar()
    return f"KW {iso.week:02d}/{iso.year}"


def _as_dict(m: ScreenerRowModel) -> dict:
    """ORM-Zeile -> schlichtes Dict, wie es `build_watchlist` erwartet."""
    return {
        "ticker": m.ticker, "name": m.name, "sector": m.sector,
        "country": m.country, "price": float(m.price) if m.price is not None else None,
        "currency": m.currency, "status": m.status, "rating": m.rating,
        "total_score": m.total_score, "trend_long": m.trend_long,
        "trend_medium": m.trend_medium, "signal_strength": m.signal_strength,
        "data_quality": m.data_quality, "drivers": m.drivers or {},
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="nur anzeigen, nichts schreiben")
    ap.add_argument("--per-priority", type=int, default=8)
    args = ap.parse_args()

    engine = create_engine()
    sm = create_session_factory(engine)

    async with sm() as session:
        rows = (await session.execute(select(ScreenerRowModel))).scalars().all()
        data = [_as_dict(r) for r in rows]
        print(f"{len(data)} Screener-Zeilen gelesen", flush=True)
        if not data:
            print("Keine Daten — Watchlist wird nicht erzeugt.", file=sys.stderr)
            await engine.dispose()
            return 1

        wl = build_watchlist(data, per_priority=args.per_priority)
        now = datetime.now(timezone.utc)

        print(f"Markt: {wl.market.breadth_verdict} "
              f"({wl.market.share_uptrend:.0%} im Aufwärtstrend)", flush=True)
        print(f"Sektoren bewertet: {len(wl.sectors)} | "
              f"Kandidaten: {len(wl.candidates)} "
              f"(aus {wl.passed_filter} gefilterten von {wl.universe_size})", flush=True)
        for p in (1, 2, 3):
            ks = [c for c in wl.candidates if c.priority == p]
            print(f"  Priorität {p}: {', '.join(k.ticker for k in ks) or '—'}", flush=True)

        if args.dry_run:
            print("\n--dry-run: nichts geschrieben.")
            await engine.dispose()
            return 0

        session.add(WeeklyWatchlistModel(
            generated_at=wl.generated_at, week_label=_week_label(now),
            payload=wl.to_dict(), n_candidates=len(wl.candidates),
            universe_size=wl.universe_size))

        # Alte Ausgaben ausdünnen, damit der Verlauf nicht unbegrenzt wächst.
        alle = (await session.execute(
            select(WeeklyWatchlistModel.generated_at)
            .order_by(WeeklyWatchlistModel.generated_at.desc()))).scalars().all()
        veraltet = list(alle)[KEEP_HISTORY:]
        for g in veraltet:
            obj = await session.get(WeeklyWatchlistModel, g)
            if obj is not None:
                await session.delete(obj)
        await session.commit()
        print(f"\nGespeichert als {_week_label(now)} ({wl.generated_at})", flush=True)
        if veraltet:
            print(f"  {len(veraltet)} alte Ausgabe(n) entfernt", flush=True)

    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
