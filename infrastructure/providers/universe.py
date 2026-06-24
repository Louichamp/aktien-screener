"""Kostenlose Ticker-Universen für den realen Ingest.

Quellen (alle gratis, ohne Key):
  * datahub S&P-500-CSV   -> ~500 Titel inkl. Name + GICS-Branche
  * rreichel US-Stock-Symbols (NASDAQ/NYSE) -> tausende Symbole (für „1.000+")

Yahoo-kompatible Symbole (Punkt -> Bindestrich, z. B. BRK.B -> BRK-B). Bei
Netzproblemen greift eine eingebettete Fallback-Liste, damit nie alles bricht.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from typing import Any

import httpx

log = logging.getLogger("screener.universe")

SP500_CSV = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
NASDAQ_JSON = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nasdaq/nasdaq_tickers.json"
NYSE_JSON = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nyse/nyse_tickers.json"

_UA = {"User-Agent": "Mozilla/5.0 (compatible; LouichampScreener/1.0)"}
_VALID = re.compile(r"^[A-Z][A-Z\-]{0,5}$")        # einfache Common-Stock-Heuristik

# Fallback, falls keine Quelle erreichbar ist (Offline/CI).
_FALLBACK: list[dict[str, Any]] = [
    {"symbol": s, "name": n, "sector": sec} for s, n, sec in [
        ("AAPL", "Apple Inc.", "Information Technology"),
        ("MSFT", "Microsoft Corp.", "Information Technology"),
        ("NVDA", "NVIDIA Corp.", "Information Technology"),
        ("AMZN", "Amazon.com Inc.", "Consumer Discretionary"),
        ("GOOGL", "Alphabet Inc.", "Communication Services"),
        ("META", "Meta Platforms Inc.", "Communication Services"),
        ("KO", "Coca-Cola Co.", "Consumer Staples"),
        ("PG", "Procter & Gamble", "Consumer Staples"),
        ("JPM", "JPMorgan Chase", "Financials"),
        ("XOM", "Exxon Mobil", "Energy"),
    ]
]


def _yahoo_symbol(sym: str) -> str:
    return sym.strip().upper().replace(".", "-").replace("/", "-")


async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    try:
        r = await client.get(url, headers=_UA, timeout=30, follow_redirects=True)
        r.raise_for_status()
        return r
    except Exception as exc:
        log.warning("Universe-Quelle nicht erreichbar (%s): %s", url, exc)
        return None


async def _fetch_sp500(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    r = await _get(client, SP500_CSV)
    if r is None:
        return []
    out: list[dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(r.text)):
        sym = row.get("Symbol")
        if not sym:
            continue
        out.append({"symbol": _yahoo_symbol(sym),
                    "name": row.get("Security"),
                    "sector": row.get("GICS Sector")})
    return out


async def _fetch_listing(client: httpx.AsyncClient, url: str) -> list[str]:
    r = await _get(client, url)
    if r is None:
        return []
    try:
        syms = r.json()
    except Exception:
        return []
    out = []
    for s in syms:
        y = _yahoo_symbol(str(s))
        if _VALID.match(y):
            out.append(y)
    return out


async def build_universe(limit: int = 1000, *, source: str = "broad") -> list[dict[str, Any]]:
    """Liefert bis zu `limit` Instrumente als [{symbol, name?, sector?}].

    source="sp500": nur der saubere S&P-500-Kern (mit Name/Branche).
    source="broad": S&P 500 zuerst, dann mit NASDAQ/NYSE bis `limit` auffüllen.
    """
    async with httpx.AsyncClient() as client:
        sp = await _fetch_sp500(client)
        seen = {d["symbol"] for d in sp}
        universe = list(sp)

        if source == "broad" and len(universe) < limit:
            extra: list[str] = []
            for url in (NASDAQ_JSON, NYSE_JSON):
                extra += await _fetch_listing(client, url)
            for sym in extra:
                if len(universe) >= limit:
                    break
                if sym not in seen:
                    seen.add(sym)
                    universe.append({"symbol": sym, "name": None, "sector": None})

    if not universe:
        log.warning("Keine Universe-Quelle erreichbar — nutze Fallback-Liste")
        universe = list(_FALLBACK)

    return universe[:limit]
