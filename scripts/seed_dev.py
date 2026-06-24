"""Befüllt eine Dev-Datenbank mit Beispiel-Screener-Zeilen.

Lauf:  DATABASE_URL=sqlite+aiosqlite:///./dev.db python scripts/seed_dev.py
Danach: uvicorn api.main:app  (liest dieselbe DATABASE_URL)
"""
from __future__ import annotations

import asyncio
import math
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.database.config import (create_engine, create_session_factory,
                                            init_models)
from infrastructure.database.models import ScreenerRowModel
from infrastructure.database.repository import compute_total_score

# (ticker, wlatar, wlafar, price, strategy, risk, trend_l, trend_m, status, rarity)
SEED = [
    ("NVDA", 9, 8, 880.0, "WACHSTUM", "hoch", "AUFWÄRTS", "AUFWÄRTS", "Breakout aktiv", "sehr selten"),
    ("MSFT", 8, 9, 420.0, "CASHFLOW", "niedrig", "AUFWÄRTS", "AUFWÄRTS", "Position verwalten", "selten"),
    ("AAPL", 8, 7, 190.0, "CASHFLOW", "niedrig", "AUFWÄRTS", "NEUTRAL", "Pullback-Einstieg", "selten"),
    ("KO", 5, 8, 60.0, "DIVIDENDE", "sehr niedrig", "AUFWÄRTS", "AUFWÄRTS", "Position verwalten", "gelegentlich"),
    ("PG", 6, 7, 160.0, "DIVIDENDE", "niedrig", "NEUTRAL", "AUFWÄRTS", "Regression abwarten", "gelegentlich"),
    ("ASML", 7, 8, 950.0, "WACHSTUM", "mittel", "AUFWÄRTS", "AUFWÄRTS", "Ausbruch vorbereitet", "selten"),
    ("HCMP", 6, 6, 25.0, "HIDDEN CHAMPION", "hoch", "AUFWÄRTS", "NEUTRAL", "Bodenbildung", "selten"),
    ("XYZ", 3, 4, 12.0, None, "sehr hoch", "ABWÄRTS", "ABWÄRTS", "Trendbruch", "häufig"),
    ("TOPV", 10, 9, 1200.0, "WACHSTUM", "hoch", "AUFWÄRTS", "AUFWÄRTS", "Breakout aktiv", "sehr selten"),
]


def targets(price: float, chance: float) -> dict:
    signal, stop, t1 = price, price * 0.95, price * 1.15
    return dict(signal_aggr=round(signal, 2), signal_kons=round(signal * 0.99, 2),
                stop_loss=round(stop, 2), target_1=round(t1, 2), target_2=round(t1 * 1.1, 2),
                crv=round((t1 - signal) / (signal - stop), 2),
                chance=chance, chance_dots=round(chance / 2))


def drivers(tkr: str, price: float) -> dict:
    return {
        "bull": [
            {"code": "trend_up", "polarity": "positive", "magnitude": 0.85,
             "statement": f"{tkr}: EMA-Konstellation klar aufwärts, ROC bestätigt die Dynamik."},
            {"code": "fund_quality", "polarity": "positive", "magnitude": 0.6,
             "statement": f"{tkr}: ROIC über Branchenschnitt, solide Nettomarge."},
        ],
        "bear": [
            {"code": "valuation", "polarity": "negative", "magnitude": 0.5,
             "statement": f"{tkr}: Bewertung sektorrelativ ambitioniert (EV/EBITDA hoch)."},
        ],
        "rationale": [f"{tkr}: Einstieg an Konfluenzzone (Fib 0.618 + EMA50).",
                      "CRV > 2 — günstiges Chance-Risiko-Verhältnis."],
        "status_note": None,
        "zones": [
            {"center": round(price * 0.98, 2), "low": round(price * 0.96, 2),
             "high": round(price * 1.0, 2), "strength": 8.4, "kind": "support",
             "categories": ["Fibonacci", "Moving Average", "Volumen"],
             "explain": "Fib 0.618 + EMA50 + VPOC", "is_entry": True},
            {"center": round(price * 1.15, 2), "low": round(price * 1.13, 2),
             "high": round(price * 1.17, 2), "strength": 6.1, "kind": "resistance",
             "categories": ["Preisniveau", "Fibonacci"],
             "explain": "Swing-Hoch + Fib-Extension 1.272", "is_entry": False},
        ],
    }


def forecast_history(price: float, horizon: int = 30, *, bullish: bool = True) -> list[dict]:
    """30-Tage-Kronos-Demoreihe: driftender Mittelpfad + weitende Bänder."""
    d0 = date(2026, 1, 2)
    drift = 0.004 if bullish else -0.003
    out = []
    for i in range(horizon):
        m = price * (1.0 + drift * i)
        half = price * 0.012 * math.sqrt(i + 1)
        out.append(dict(timestamp=(d0 + timedelta(days=i)).isoformat(),
                        mean=round(m, 4), upper=round(m + half, 4), lower=round(m - half, 4)))
    return out


async def main() -> None:
    engine = create_engine()
    await init_models(engine)
    sm = create_session_factory(engine)
    async with sm() as s:
        for tkr, ta, fa, price, strat, risk, tl, tm, status, rarity in SEED:
            await s.merge(ScreenerRowModel(
                ticker=tkr, price=price, currency="USD",
                strategy_tag=strat, strategy_tags=[strat] if strat else [],
                status=status, wlatar=ta, wlafar=fa,
                total_score=compute_total_score(ta, fa),
                trend_long=tl, trend_medium=tm, risikoklasse=risk, chance_rarity=rarity,
                targets=targets(price, float(ta)), drivers=drivers(tkr, price),
                forecast_history=forecast_history(price, bullish=(tl != "ABWÄRTS")),
            ))
        await s.commit()
    await engine.dispose()
    print(f"seeded {len(SEED)} rows into {os.getenv('DATABASE_URL')}")


if __name__ == "__main__":
    asyncio.run(main())
