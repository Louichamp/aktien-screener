"""Erzeugt ein großes Demo-Universum (Default 1.000 Instrumente).

Damit lässt sich das Dashboard mit realistischer Größe testen: Filter, Sortierung
und Paging über 1.000+ Zeilen. Deterministisch (fester Seed) — reproduzierbar.

  DATABASE_URL=sqlite+aiosqlite:///./dev.db python scripts/seed_universe.py --count 1000
"""
from __future__ import annotations

import argparse
import asyncio
import math
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete

from infrastructure.database.config import (create_engine, create_session_factory,
                                            init_models)
from infrastructure.database.models import ScreenerRowModel
from infrastructure.database.repository import compute_total_score, rating_label

SECTORS = ["Technologie", "Gesundheit", "Finanzen", "Energie", "Industrie",
           "Konsumgüter", "Kommunikation", "Rohstoffe", "Versorger", "Immobilien"]
COUNTRIES = [("USA", "Inc."), ("Deutschland", "AG"), ("Niederlande", "N.V."),
             ("Schweden", "AB"), ("Frankreich", "S.A."), ("Schweiz", "AG"),
             ("Kanada", "Inc."), ("Japan", "K.K."), ("Großbritannien", "plc")]
STATUSES = ["Boden abwarten", "Bodenbildung", "Ausbruch vorbereitet", "Breakout aktiv",
            "Pullback-Einstieg", "Position verwalten", "Regression abwarten",
            "Dynamikverlust", "Trendbruch", "Vermeiden"]
RISK = ["sehr niedrig", "niedrig", "mittel", "hoch", "sehr hoch"]
RARITY = ["alltäglich", "häufig", "gelegentlich", "selten", "sehr selten"]
ASSET_WEIGHTED = ["Aktie"] * 80 + ["ETF"] * 12 + ["Krypto"] * 5 + ["Forex"] * 3
NAME_PREFIX = ["Global", "United", "Nordic", "Atlantic", "Pioneer", "Vertex", "Summit",
               "Apex", "Helios", "Orion", "Cascade", "Meridian", "Quantum", "Vanguard",
               "Keystone", "Lumen", "Solaris", "Aurora", "Titan", "Catalyst"]
NAME_CORE = {"Technologie": ["Systems", "Microelectronics", "Robotics", "Cloud", "Semiconductor"],
             "Gesundheit": ["Therapeutics", "BioSciences", "Medical", "Pharma", "HealthCare"],
             "Finanzen": ["Capital", "Financial", "Bancorp", "Holdings", "Investments"],
             "Energie": ["Energy", "Petroleum", "Renewables", "Power", "Resources"],
             "Industrie": ["Industries", "Manufacturing", "Engineering", "Logistics", "Aerospace"],
             "Konsumgüter": ["Consumer", "Brands", "Foods", "Beverage", "Retail"],
             "Kommunikation": ["Communications", "Media", "Networks", "Telecom", "Interactive"],
             "Rohstoffe": ["Materials", "Mining", "Chemicals", "Metals", "Forest"],
             "Versorger": ["Utilities", "Water", "Grid", "Electric", "Gas"],
             "Immobilien": ["Realty", "Properties", "REIT", "Estates", "Development"]}

# Ein paar echte Schwergewichte für den Wiedererkennungswert.
REAL = [
    ("AAPL", "Apple Inc.", "Technologie", "USA"), ("MSFT", "Microsoft Corp.", "Technologie", "USA"),
    ("NVDA", "NVIDIA Corp.", "Technologie", "USA"), ("ASML", "ASML Holding N.V.", "Technologie", "Niederlande"),
    ("KO", "Coca-Cola Co.", "Konsumgüter", "USA"), ("PG", "Procter & Gamble", "Konsumgüter", "USA"),
    ("SAP", "SAP SE", "Technologie", "Deutschland"), ("NOVO", "Novo Nordisk A/S", "Gesundheit", "Dänemark"),
    ("NESN", "Nestlé S.A.", "Konsumgüter", "Schweiz"), ("SHEL", "Shell plc", "Energie", "Großbritannien"),
]


def _forecast(price: float, bullish: bool, horizon: int = 30) -> list[dict]:
    d0 = date(2026, 1, 2)
    drift = 0.004 if bullish else -0.003
    return [dict(timestamp=(d0 + timedelta(days=i)).isoformat(),
                 mean=round(price * (1 + drift * i), 4),
                 upper=round(price * (1 + drift * i) + price * 0.012 * math.sqrt(i + 1), 4),
                 lower=round(price * (1 + drift * i) - price * 0.012 * math.sqrt(i + 1), 4))
            for i in range(horizon)]


def _drivers(name: str, sector: str, price: float) -> dict:
    return {
        "bull": [{"code": "trend_up", "polarity": "positive", "magnitude": 0.8,
                  "statement": f"{name}: EMA-Konstellation aufwärts, Momentum bestätigt."},
                 {"code": "sector", "polarity": "positive", "magnitude": 0.55,
                  "statement": f"Relative Stärke im Sektor {sector}."}],
        "bear": [{"code": "valuation", "polarity": "negative", "magnitude": 0.45,
                  "statement": f"{name}: Bewertung sektorrelativ erhöht."}],
        "rationale": [f"{name}: Einstieg an Konfluenzzone (Fib 0.618 + EMA50)."],
        "status_note": None,
        "zones": [{"center": round(price * 0.98, 2), "low": round(price * 0.96, 2),
                   "high": round(price, 2), "strength": 8.0, "kind": "support",
                   "categories": ["Fibonacci", "Moving Average", "Volumen"],
                   "explain": "Fib 0.618 + EMA50 + VPOC", "is_entry": True}],
    }


def build_rows(count: int, seed: int = 42) -> list[ScreenerRowModel]:
    rng = random.Random(seed)
    rows: list[ScreenerRowModel] = []
    used: set[str] = set()

    def make(ticker: str, name: str, sector: str, country: str, asset: str):
        wlatar = rng.randint(1, 10)
        wlafar = max(1, min(10, wlatar + rng.randint(-3, 3)))
        total = compute_total_score(wlatar, wlafar)
        bullish = wlatar >= 5
        trend_l = "AUFWÄRTS" if wlatar >= 6 else "ABWÄRTS" if wlatar <= 3 else "NEUTRAL"
        trend_m = "AUFWÄRTS" if wlafar >= 6 else "ABWÄRTS" if wlafar <= 3 else "NEUTRAL"
        price = round(rng.uniform(5, 1500), 2)
        # Strategie grob aus Profil ableiten (mit Leerwerten für Realismus).
        div = round(rng.choice([0.0, 0.0, 0.008, 0.018, 0.025, 0.035, 0.05]), 4)
        if div >= 0.025 and wlafar >= 5:
            strat = "DIVIDENDE"
        elif wlatar >= 7 and wlafar >= 5:
            strat = "WACHSTUM"
        elif wlafar >= 7:
            strat = "CASHFLOW"
        elif 3e8 <= price * 1e7 <= 1e10 and wlafar >= 6:
            strat = "HIDDEN CHAMPION"
        else:
            strat = rng.choice([None, None, "WACHSTUM", "CASHFLOW"])
        risk = RISK[min(4, max(0, 5 - (wlatar // 2) + rng.randint(-1, 1)))]
        signal = price
        stop = round(price * rng.uniform(0.9, 0.97), 2)
        t1 = round(price * rng.uniform(1.08, 1.25), 2)
        chance = float(min(10, max(0, round(wlatar * 0.7 + rng.uniform(0, 3)))))
        rows.append(ScreenerRowModel(
            ticker=ticker, name=name, sector=sector, country=country, asset_class=asset,
            price=price, currency="USD" if country == "USA" else "EUR",
            dividend_yield=div or None,
            strategy_tag=strat, strategy_tags=[strat] if strat else [],
            status=rng.choice(STATUSES), rating=rating_label(total),
            wlatar=wlatar, wlafar=wlafar, total_score=total,
            trend_long=trend_l, trend_medium=trend_m, risikoklasse=risk,
            chance_rarity=rng.choice(RARITY),
            targets=dict(signal_aggr=signal, signal_kons=round(signal * 0.99, 2),
                         stop_loss=stop, target_1=t1, target_2=round(t1 * 1.1, 2),
                         crv=round((t1 - signal) / (signal - stop), 2) if signal > stop else None,
                         chance=chance, chance_dots=round(chance / 2)),
            drivers=_drivers(name, sector, price),
            forecast_history=_forecast(price, bullish)))

    for tkr, name, sector, country in REAL:
        if len(rows) >= count:
            break
        used.add(tkr)
        make(tkr, name, sector, country, "Aktie")

    i = 0
    while len(rows) < count:
        sector = SECTORS[i % len(SECTORS)]
        country, suffix = COUNTRIES[i % len(COUNTRIES)]
        asset = rng.choice(ASSET_WEIGHTED)
        name = f"{rng.choice(NAME_PREFIX)} {rng.choice(NAME_CORE[sector])} {suffix}"
        # eindeutiger Ticker
        ticker = f"{name[:3].upper()}{i:04d}"
        while ticker in used:
            ticker = f"X{i:04d}{rng.randint(0,9)}"
        used.add(ticker)
        make(ticker, name, sector, country, asset)
        i += 1
    return rows


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    engine = create_engine()
    await init_models(engine)
    sm = create_session_factory(engine)
    rows = build_rows(args.count, args.seed)
    async with sm() as s:
        await s.execute(delete(ScreenerRowModel))    # Demo-Universum frisch aufbauen
        s.add_all(rows)
        await s.commit()
    await engine.dispose()
    print(f"seeded {len(rows)} instruments into {os.getenv('DATABASE_URL')}")


if __name__ == "__main__":
    asyncio.run(main())
