"""Kostenloser Markt-/Fundamentaldaten-Provider auf Basis von Yahoo Finance.

Yahoo (über `yfinance`) braucht KEINEN API-Key und liefert OHLCV, Stammdaten,
Fundamentaldaten und News — ideal, um das volle Universum (1.000+ Titel) gratis
zu beschaffen. `yfinance` ist synchron; alle Calls laufen daher in einem
Thread-Executor (`asyncio.to_thread`) und sind über ein Semaphore gedrosselt,
damit Yahoo nicht throttelt.

Implementiert dasselbe Protokoll wie der FMP-Provider (`fetch`, `fetch_news`,
`aclose`) und ist damit drop-in im Worker/News-Endpunkt.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from screener.zones import Candle
from screener.pipeline import MarketSnapshot

from .indicators import technicals_from_candles

log = logging.getLogger("screener.provider.yahoo")

_QUOTE_TYPE = {"EQUITY": "Aktie", "ETF": "ETF", "MUTUALFUND": "Fonds",
               "CRYPTOCURRENCY": "Krypto", "CURRENCY": "Forex", "INDEX": "Index"}


def _f(v: Any) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return f if f == f else None          # NaN raus
    except (TypeError, ValueError):
        return None


class YahooMarketDataProvider:
    """Holt einen `MarketSnapshot` je Ticker von Yahoo Finance (kostenlos)."""

    def __init__(self, *, period: str = "2y", max_concurrency: int | None = None,
                 with_fundamentals: bool = True, keep_candles: int | None = None) -> None:
        self.period = period or os.getenv("YF_PERIOD", "2y")
        self.with_fundamentals = with_fundamentals
        # Nach der Indikator-Berechnung nur die jüngsten N Kerzen behalten:
        # spart bei 5.000+ Titeln massiv Speicher (Zonen brauchen ~1 Jahr).
        self.keep_candles = keep_candles if keep_candles is not None else int(
            os.getenv("YF_KEEP_CANDLES", "260"))
        self._sem = asyncio.Semaphore(
            max_concurrency or int(os.getenv("YF_MAX_CONCURRENCY", "8")))

    async def aclose(self) -> None:                # API-Kompatibilität (kein Client offen)
        return None

    # ------------------------------------------------------------------ #
    def _candles_from_history(self, hist: Any) -> list[Candle]:
        candles: list[Candle] = []
        for row in hist.itertuples(index=False):
            o, h, l, c = _f(row.Open), _f(row.High), _f(row.Low), _f(row.Close)
            v = _f(getattr(row, "Volume", 0.0)) or 0.0
            if None in (o, h, l, c):
                continue
            candles.append(Candle(o=o, h=h, l=l, c=c, v=v))
        return candles

    def _fundamentals(self, info: dict[str, Any]) -> dict[str, float]:
        fcf = _f(info.get("freeCashflow"))
        rev = _f(info.get("totalRevenue"))
        mcap = _f(info.get("marketCap"))
        d2e = _f(info.get("debtToEquity"))
        out = {
            "net_margin": _f(info.get("profitMargins")),
            "roic": _f(info.get("returnOnEquity")),          # ROE als ROIC-Näherung
            "debt_to_equity": (d2e / 100.0) if d2e is not None else None,  # Yahoo gibt %
            "revenue_growth": _f(info.get("revenueGrowth")),
            "eps_growth": _f(info.get("earningsGrowth")),
            "pe": _f(info.get("trailingPE")),
            "ev_ebitda": _f(info.get("enterpriseToEbitda")),
            "p_b": _f(info.get("priceToBook")),
            "free_cash_flow": fcf,
            "dividend_yield": _f(info.get("trailingAnnualDividendYield")),
        }
        if fcf and rev:
            out["fcf_margin"] = fcf / rev
        if fcf and mcap and fcf > 0:
            out["p_fcf"] = mcap / fcf
        # Dividenden-Fallback: Rate/Preis, falls Yield fehlt.
        if out["dividend_yield"] is None:
            rate, price = _f(info.get("dividendRate")), _f(info.get("currentPrice"))
            if rate and price:
                out["dividend_yield"] = rate / price
        return {k: v for k, v in out.items() if v is not None}

    def _fetch_sync(self, ticker: str) -> MarketSnapshot | None:
        import yfinance as yf

        t = yf.Ticker(ticker)
        hist = t.history(period=self.period, interval="1d", auto_adjust=True)
        if hist is None or len(hist) < 2:
            return None
        candles = self._candles_from_history(hist)
        if not candles:
            return None

        info: dict[str, Any] = {}
        if self.with_fundamentals:
            try:
                info = t.get_info() or {}
            except Exception as exc:                # Fundamentaldaten optional
                log.debug("yahoo info %s nicht verfügbar: %s", ticker, exc)

        price = _f(info.get("currentPrice")) or candles[-1].c
        technicals = technicals_from_candles(candles, price=price)
        if self.keep_candles and len(candles) > self.keep_candles:
            candles = candles[-self.keep_candles:]    # Speicher sparen (Indikatoren stehen schon)
        avg_vol = _f(info.get("averageVolume"))
        return MarketSnapshot(
            instrument_id=ticker, ticker=ticker,
            name=info.get("longName") or info.get("shortName") or ticker,
            country=info.get("country"),
            asset_class=_QUOTE_TYPE.get(info.get("quoteType", ""), "Aktie"),
            sector=info.get("sector"),
            industry=info.get("industry"),
            market_cap=_f(info.get("marketCap")),
            currency=info.get("currency") or "USD",
            price=price,
            technicals=technicals,
            fundamentals=self._fundamentals(info) if info else {},
            candles=candles,
            avg_dollar_volume=(avg_vol * price) if avg_vol else None,
        )

    async def fetch(self, ticker: str) -> MarketSnapshot | None:
        async with self._sem:
            try:
                return await asyncio.to_thread(self._fetch_sync, ticker)
            except Exception as exc:
                log.warning("yahoo fetch %s fehlgeschlagen: %s", ticker, exc)
                return None

    # ------------------------------------------------------------------ #
    def _news_sync(self, ticker: str, limit: int) -> list[dict[str, Any]]:
        import yfinance as yf

        raw = yf.Ticker(ticker).news or []
        items: list[dict[str, Any]] = []
        for it in raw[:limit]:
            c = it.get("content") if isinstance(it.get("content"), dict) else it
            url = (((c.get("canonicalUrl") or {}).get("url") if isinstance(c.get("canonicalUrl"), dict) else None)
                   or ((c.get("clickThroughUrl") or {}).get("url") if isinstance(c.get("clickThroughUrl"), dict) else None)
                   or it.get("link"))
            source = (((c.get("provider") or {}).get("displayName") if isinstance(c.get("provider"), dict) else None)
                      or it.get("publisher"))
            pub = c.get("pubDate") or it.get("providerPublishTime")
            title = c.get("title") or it.get("title")
            if not title:
                continue
            items.append({"title": title, "url": url, "source": source,
                          "published_at": str(pub) if pub is not None else None,
                          "snippet": c.get("summary") or c.get("description"),
                          "image": None})
        return items

    async def fetch_news(self, ticker: str, *, limit: int = 20) -> list[dict[str, Any]]:
        async with self._sem:
            return await asyncio.to_thread(self._news_sync, ticker, limit)
