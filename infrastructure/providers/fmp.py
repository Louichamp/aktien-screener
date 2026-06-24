"""Echter Markt-/Fundamentaldaten-Provider auf Basis von Financial Modeling Prep.

Beschafft je Instrument Profil, Quote, historische OHLCV (-> technische
Indikatoren) sowie TTM-Kennzahlen und Wachstum (-> Fundamentaldaten) und baut
daraus einen `MarketSnapshot`. Ein async Rate-Limiter (Anfragen/Minute +
Nebenläufigkeits-Semaphore) hält die FMP-Limits ein; 429/5xx werden mit
Exponential-Backoff wiederholt.

Konfiguration (Umgebung):
  FMP_API_KEY            Pflicht
  FMP_BASE_URL           Default https://financialmodelingprep.com/api/v3
  FMP_RATE_LIMIT         Anfragen/Minute (Default 300)
  FMP_MAX_CONCURRENCY    parallele Requests (Default 8)
  FMP_HISTORY_DAYS       Kerzen-Tiefe für Indikatoren (Default 300)
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from typing import Any

import httpx

from screener.zones import Candle
from screener.pipeline import MarketSnapshot

from .indicators import technicals_from_candles

log = logging.getLogger("screener.provider.fmp")


def _f(d: dict[str, Any], *keys: str) -> float | None:
    """Erster vorhandener, in float konvertierbarer Wert (FMP-Feldnamen variieren)."""
    for k in keys:
        v = d.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


class AsyncRateLimiter:
    """Token-Fenster (max N Anfragen / `period` Sekunden) + Concurrency-Limit."""

    def __init__(self, rate_per_min: int, max_concurrency: int) -> None:
        self._rate = max(1, rate_per_min)
        self._period = 60.0
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(max(1, max_concurrency))

    async def __aenter__(self) -> "AsyncRateLimiter":
        await self._sem.acquire()
        # Slot unter dem Lock reservieren (Zeitstempel der frühesten Ausführung),
        # dann den Lock freigeben und außerhalb warten -> kein Serialisieren der
        # Nebenläufigkeit, kein Thundering-Herd (jeder Caller bekommt einen Slot).
        async with self._lock:
            now = time.monotonic()
            while self._calls and now - self._calls[0] >= self._period:
                self._calls.popleft()
            wait = 0.0
            if len(self._calls) >= self._rate:
                wait = self._period - (now - self._calls[0])
            self._calls.append(now + max(0.0, wait))
        if wait > 0:
            await asyncio.sleep(wait)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self._sem.release()


class FMPMarketDataProvider:
    """Implementiert das `MarketDataProvider`-Protokoll gegen die FMP-API."""

    def __init__(self, api_key: str | None = None, *, base_url: str | None = None,
                 rate_per_min: int | None = None, max_concurrency: int | None = None,
                 history_days: int | None = None, timeout: float = 20.0) -> None:
        self.api_key = api_key or os.getenv("FMP_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("FMP_API_KEY fehlt — echten Provider nur mit Key starten")
        self.base_url = (base_url or os.getenv(
            "FMP_BASE_URL", "https://financialmodelingprep.com/api/v3")).rstrip("/")
        self.history_days = history_days or int(os.getenv("FMP_HISTORY_DAYS", "300"))
        self._limiter = AsyncRateLimiter(
            rate_per_min or int(os.getenv("FMP_RATE_LIMIT", "300")),
            max_concurrency or int(os.getenv("FMP_MAX_CONCURRENCY", "8")))
        self._client = httpx.AsyncClient(
            base_url=self.base_url, timeout=timeout,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10))

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---- HTTP mit Throttle + Retry -------------------------------------
    async def _get(self, path: str, *, params: dict[str, Any] | None = None,
                   attempts: int = 3) -> Any:
        q = {"apikey": self.api_key, **(params or {})}
        last: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                async with self._limiter:
                    resp = await self._client.get(path, params=q)
                # 429/5xx sind transient -> Retry; andere 4xx (404, 401, 403) sind
                # terminal -> sofort None (kein Sinn, einen Tippfehler-Ticker zu wiederholen).
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"FMP {resp.status_code}", request=resp.request, response=resp)
                if resp.status_code >= 400:
                    log.info("FMP %s -> %s (terminal, übersprungen)", path, resp.status_code)
                    return None
                return resp.json()
            except (httpx.HTTPError, asyncio.TimeoutError, ValueError) as exc:
                last = exc                          # ValueError deckt JSON-Decode-Fehler ab
                if attempt < attempts:
                    await asyncio.sleep(1.5 ** attempt)
        log.warning("FMP %s endgültig fehlgeschlagen: %s", path, last)
        return None

    @staticmethod
    def _first(payload: Any) -> dict[str, Any]:
        if isinstance(payload, list) and payload:
            return payload[0]
        if isinstance(payload, dict):
            return payload
        return {}

    # ---- Candle-Beschaffung --------------------------------------------
    async def _candles(self, ticker: str) -> list[Candle]:
        data = await self._get(f"/historical-price-full/{ticker}",
                               params={"timeseries": self.history_days})
        hist = (data or {}).get("historical") or []
        # FMP liefert neueste zuerst -> chronologisch (alt -> neu) drehen.
        candles: list[Candle] = []
        for row in reversed(hist):
            try:
                candles.append(Candle(
                    o=float(row["open"]), h=float(row["high"]), l=float(row["low"]),
                    c=float(row["close"]), v=float(row.get("volume") or 0.0)))
            except (KeyError, TypeError, ValueError):
                continue
        return candles

    # ---- News (live, für das Tearsheet) --------------------------------
    async def fetch_news(self, ticker: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Aktuelle Nachrichten zu einem Ticker -> normalisierte News-Dicts."""
        data = await self._get("/stock_news", params={"tickers": ticker, "limit": limit})
        items: list[dict[str, Any]] = []
        for row in (data or []):
            if not isinstance(row, dict):
                continue
            items.append({
                "title": row.get("title") or "",
                "url": row.get("url"),
                "source": row.get("site"),
                "published_at": row.get("publishedDate"),
                "snippet": row.get("text"),
                "image": row.get("image"),
            })
        return [i for i in items if i["title"]]

    async def fetch_universe(self, *, limit: int = 1000, min_market_cap: float = 2e9,
                             exchanges: str = "NYSE,NASDAQ") -> list[str]:
        """Liefert ein handelbares Universum von Tickern (FMP-Screener).

        Standard: die `limit` größten Titel an NYSE/NASDAQ über `min_market_cap`.
        Damit lässt sich die WATCHLIST produktiv auf 1.000+ Werte heben.
        """
        data = await self._get("/stock-screener", params={
            "marketCapMoreThan": int(min_market_cap), "exchange": exchanges,
            "isActivelyTrading": "true", "limit": limit})
        out: list[str] = []
        for row in (data or []):
            sym = isinstance(row, dict) and row.get("symbol")
            if sym:
                out.append(str(sym))
        return out

    async def fetch_constituents(self, index: str) -> list[dict[str, Any]]:
        """Index-Mitglieder (S&P 500, NASDAQ 100, Dow). index in {sp500,nasdaq,dowjones}.

        Liefert je {symbol, name, sector} — Name/Branche kommen schon mit, ohne
        je Ticker einen Extra-Call zu brauchen.
        """
        data = await self._get(f"/{index}_constituent")
        out: list[dict[str, Any]] = []
        for row in (data or []):
            if isinstance(row, dict) and row.get("symbol"):
                out.append({"symbol": str(row["symbol"]),
                            "name": row.get("name"), "sector": row.get("sector")})
        return out

    async def fetch_profile_meta(self, ticker: str) -> dict[str, Any] | None:
        """Leichtgewichtige Stammdaten aus /profile (ein Call): Name, Branche,
        Land, Währung, Preis, Dividendenrendite, Anlageklasse."""
        prof = self._first(await self._get(f"/profile/{ticker}"))
        if not prof:
            return None
        price = _f(prof, "price")
        last_div = _f(prof, "lastDiv")
        div_yield = (last_div / price) if (last_div and price) else None
        is_etf = bool(prof.get("isEtf"))
        is_fund = bool(prof.get("isFund"))
        return {
            "name": prof.get("companyName") or ticker,
            "sector": prof.get("sector") or None,
            "country": prof.get("country") or None,
            "currency": prof.get("currency") or "USD",
            "price": price,
            "dividend_yield": round(div_yield, 5) if div_yield else None,
            "asset_class": "ETF" if (is_etf or is_fund) else "Aktie",
        }

    # ---- Hauptmethode (Protokoll) --------------------------------------
    async def fetch(self, ticker: str) -> MarketSnapshot | None:
        # Alle Calls parallel (durch Limiter gedrosselt). return_exceptions=True:
        # ein fehlschlagender Endpoint (z. B. fehlende Fundamentaldaten) darf den
        # Snapshot nicht killen — er wird dann nur dünner befüllt.
        results = await asyncio.gather(
            self._get(f"/profile/{ticker}"),
            self._get(f"/quote/{ticker}"),
            self._candles(ticker),
            self._get(f"/ratios-ttm/{ticker}"),
            self._get(f"/key-metrics-ttm/{ticker}"),
            self._get(f"/financial-growth/{ticker}", params={"limit": 1}),
            return_exceptions=True,
        )
        safe: list[Any] = []
        for r in results:
            if isinstance(r, BaseException):
                log.warning("FMP %s: Teil-Call fehlgeschlagen: %s", ticker, r)
                safe.append(None)
            else:
                safe.append(r)
        profile_p, quote_p, candles_p, ratios_p, metrics_p, growth_p = safe
        profile = self._first(profile_p)
        quote = self._first(quote_p)
        ratios = self._first(ratios_p)
        metrics = self._first(metrics_p)
        growth = self._first(growth_p)
        candles = candles_p if isinstance(candles_p, list) else []

        price = _f(quote, "price") or _f(profile, "price") or (candles[-1].c if candles else 0.0)
        if not price:
            log.info("FMP: kein Preis für %s — übersprungen", ticker)
            return None

        technicals = technicals_from_candles(candles, price=price)
        # avg_dollar_volume aus Quote (Fallback: aus Kerzen)
        avg_vol = _f(quote, "avgVolume", "avgVolume10Day")
        adv = (avg_vol * price) if avg_vol else None

        # Fundamentaldaten defensiv mappen (FMP-Feldnamen variieren je Endpoint/Version)
        fcf_ps = _f(metrics, "freeCashFlowPerShareTTM", "freeCashFlowPerShare")
        rev_ps = _f(metrics, "revenuePerShareTTM", "revenuePerShare")
        shares = _f(quote, "sharesOutstanding") or (
            (_f(quote, "marketCap") or 0.0) / price if price else None)
        fundamentals = {
            "revenue_growth": _f(growth, "revenueGrowth"),
            "eps_growth": _f(growth, "epsgrowth", "epsGrowth"),
            "dividend_yield": _f(ratios, "dividendYieldTTM", "dividendYielPercentageTTM"),
            "net_margin": _f(ratios, "netProfitMarginTTM"),
            "debt_to_equity": _f(ratios, "debtEquityRatioTTM", "debtToEquityTTM"),
            "pe": _f(ratios, "peRatioTTM", "priceEarningsRatioTTM"),
            "p_b": _f(ratios, "priceToBookRatioTTM", "pbRatioTTM"),
            "p_fcf": _f(ratios, "priceToFreeCashFlowsRatioTTM", "pfcfRatioTTM"),
            "ev_ebitda": _f(metrics, "enterpriseValueOverEBITDATTM", "evToEbitdaTTM"),
            "roic": _f(metrics, "roicTTM", "returnOnInvestedCapitalTTM"),
        }
        if fcf_ps is not None and rev_ps:
            fundamentals["fcf_margin"] = fcf_ps / rev_ps if rev_ps else None
        if fcf_ps is not None and shares:
            fundamentals["free_cash_flow"] = fcf_ps * shares
        fundamentals = {k: v for k, v in fundamentals.items() if v is not None}

        return MarketSnapshot(
            instrument_id=ticker, ticker=ticker,
            name=profile.get("companyName") or quote.get("name") or ticker,
            country=profile.get("country") or None,
            asset_class="stock",
            sector=profile.get("sector") or None,
            industry=profile.get("industry") or None,
            market_cap=_f(quote, "marketCap") or _f(profile, "mktCap"),
            currency=profile.get("currency") or "USD",
            price=price,
            technicals=technicals,
            fundamentals=fundamentals,
            candles=candles,
            avg_dollar_volume=adv,
        )
