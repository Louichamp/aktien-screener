"""Async-Tests der Lese-Schicht gegen eine echte (SQLite-)Datenbank.

Bewiesen wird, dass Filterung, Sortierung (nach Scores) und Paging *auf der
Datenbank* passieren: Wir säen ein kleines Universum, fragen über den
httpx-ASGI-Client ab und prüfen Reihenfolge, Filtermenge und `total`/Fenster.
Ein zusätzlicher Test kompiliert die Query und zeigt ORDER BY/LIMIT/OFFSET im
generierten SQL (= Push-down, nicht Python-seitiges Slicen).

Lauf:  pytest -q          oder      python tests/test_api.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

# Projekt-Root importierbar machen (falls ohne Installation gestartet).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.main import create_app                                   # noqa: E402
from api.queries import query_screener_rows                        # noqa: E402
from infrastructure.database.config import (create_engine,         # noqa: E402
                                            create_session_factory, init_models)
from infrastructure.database.models import ScreenerRowModel        # noqa: E402
from infrastructure.database.repository import (ScreenerRepository,  # noqa: E402
                                                compute_total_score, rating_label)
from api.queries import ScreenerFilters, query_facets                # noqa: E402
from api.cache import TTLCache                                       # noqa: E402
from screener.pipeline import MarketSnapshot, run_screener_pipeline  # noqa: E402
from screener.zones import Candle                                  # noqa: E402

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- #
#  Seed-Universum: bewusst variierte Scores/Strategien/Risikoklassen
# --------------------------------------------------------------------------- #
def _targets(signal: float, stop: float, t1: float, chance: float) -> dict:
    crv = round((t1 - signal) / (signal - stop), 2) if signal > stop else None
    return dict(signal_aggr=signal, signal_kons=signal * 0.99, stop_loss=stop,
                target_1=t1, target_2=t1 * 1.1, crv=crv,
                chance=chance, chance_dots=round(chance / 2))


def _drivers(ticker: str) -> dict:
    return {
        "bull": [{"code": "trend_up", "polarity": "positive",
                  "magnitude": 0.8, "statement": f"{ticker}: intakter Aufwärtstrend"}],
        "bear": [{"code": "valuation", "polarity": "negative",
                  "magnitude": 0.4, "statement": f"{ticker}: ambitionierte Bewertung"}],
        "rationale": [f"{ticker}: Einstieg an Konfluenzzone"],
        "status_note": None,
        "zones": [{"center": 100.0, "low": 98.0, "high": 102.0, "strength": 8.2,
                   "kind": "support", "categories": ["Fibonacci", "Moving Average"],
                   "explain": "Fib 0.618 + EMA50", "is_entry": True}],
    }


# (ticker, wlatar, wlafar, price, strategy_tag, risikoklasse)
_SEED = [
    ("NVDA", 9, 8, 880.0, "WACHSTUM", "hoch"),
    ("MSFT", 8, 9, 420.0, "CASHFLOW", "niedrig"),
    ("AAPL", 8, 7, 190.0, "CASHFLOW", "niedrig"),
    ("KO",   5, 8, 60.0,  "DIVIDENDE", "sehr niedrig"),
    ("PG",   6, 7, 160.0, "DIVIDENDE", "niedrig"),
    ("ASML", 7, 8, 950.0, "WACHSTUM", "mittel"),
    ("ADBE", 7, 7, 560.0, "WACHSTUM", "mittel"),
    ("HCMP", 6, 6, 25.0,  "HIDDEN CHAMPION", "hoch"),
    ("XYZ",  3, 4, 12.0,  None, "sehr hoch"),
    ("LOWV", 2, 3, 8.0,   None, "sehr hoch"),
    ("MIDV", 4, 5, 40.0,  "CASHFLOW", "mittel"),
    ("TOPV", 10, 9, 1200.0, "WACHSTUM", "hoch"),
]


_SECTORS = ["Technology", "Healthcare", "Financials", "Energy", "Consumer"]
_COUNTRIES = ["USA", "Deutschland", "Niederlande", "Schweden", "Kanada"]


async def _seed(sessionmaker) -> None:
    async with sessionmaker() as s:
        for i, (tkr, ta, fa, price, tag, risk) in enumerate(_SEED):
            total = compute_total_score(ta, fa)
            s.add(ScreenerRowModel(
                ticker=tkr, name=f"{tkr} Inc.", sector=_SECTORS[i % len(_SECTORS)],
                country=_COUNTRIES[i % len(_COUNTRIES)], asset_class="stock",
                price=price, currency="USD", dividend_yield=round(0.005 * (i % 6), 4),
                strategy_tag=tag, strategy_tags=[tag] if tag else [],
                status="Breakout aktiv", rating=rating_label(total), wlatar=ta, wlafar=fa,
                total_score=total,
                trend_long="AUFWÄRTS", trend_medium="AUFWÄRTS",
                risikoklasse=risk, chance_rarity="selten",
                targets=_targets(price, price * 0.95, price * 1.15, chance=float(ta)),
                drivers=_drivers(tkr),
            ))
        await s.commit()


# --------------------------------------------------------------------------- #
#  Fixtures
# --------------------------------------------------------------------------- #
@pytest_asyncio.fixture
async def app_and_db():
    tmp = tempfile.TemporaryDirectory()
    url = f"sqlite+aiosqlite:///{Path(tmp.name) / 'screener.db'}"
    engine = create_engine(url)
    await init_models(engine)
    sessionmaker = create_session_factory(engine)
    await _seed(sessionmaker)

    # State direkt setzen (ASGI-Lifespan wird vom Test-Transport nicht ausgelöst).
    app = create_app(url)
    app.state.db_engine = engine
    app.state.sessionmaker = sessionmaker

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, sessionmaker

    await engine.dispose()
    tmp.cleanup()


# --------------------------------------------------------------------------- #
#  Tests
# --------------------------------------------------------------------------- #
async def test_sort_desc_by_wlatar(app_and_db):
    client, _ = app_and_db
    r = await client.get("/api/v1/screener", params={"sort_by": "wlatar", "limit": 100})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == len(_SEED)
    wlatars = [row["wlatar"] for row in body["items"]]
    assert wlatars == sorted(wlatars, reverse=True), "wlatar absteigend"
    assert body["items"][0]["ticker"] == "TOPV"      # höchster wlatar=10


async def test_default_sort_is_total_score(app_and_db):
    client, _ = app_and_db
    body = (await client.get("/api/v1/screener", params={"limit": 100})).json()
    scores = [row["total_score"] for row in body["items"]]
    assert scores == sorted(scores, reverse=True), "Standard: Gesamtrating absteigend"


async def test_filter_by_strategy(app_and_db):
    client, _ = app_and_db
    r = await client.get("/api/v1/screener", params={"strategy": "WACHSTUM", "limit": 100})
    body = r.json()
    tags = {row["strategy_tag"] for row in body["items"]}
    assert tags == {"WACHSTUM"}
    assert body["total"] == sum(1 for s in _SEED if s[4] == "WACHSTUM")


async def test_filter_by_risk_class(app_and_db):
    client, _ = app_and_db
    r = await client.get("/api/v1/screener", params={"risk_class": "niedrig", "limit": 100})
    body = r.json()
    assert {row["risikoklasse"] for row in body["items"]} == {"niedrig"}
    assert body["total"] == sum(1 for s in _SEED if s[5] == "niedrig")


async def test_sort_by_total_score_desc(app_and_db):
    client, _ = app_and_db
    r = await client.get("/api/v1/screener",
                         params={"sort_by": "total_score", "sort_dir": "desc", "limit": 100})
    body = r.json()
    scores = [row["total_score"] for row in body["items"]]
    assert scores == sorted(scores, reverse=True), "Gesamtrating absteigend"
    # TOPV: 0.6*10 + 0.4*9 = 9.6 -> 96 (höchster)
    assert body["items"][0]["ticker"] == "TOPV"
    assert body["items"][0]["total_score"] == 96


async def test_sort_by_price_asc(app_and_db):
    client, _ = app_and_db
    r = await client.get("/api/v1/screener",
                         params={"sort_by": "price", "sort_dir": "asc", "limit": 100})
    prices = [row["price"] for row in r.json()["items"]]
    assert prices == sorted(prices), "Preis aufsteigend"


async def test_pagination_window_and_total(app_and_db):
    client, _ = app_and_db
    # Volle, sortierte Referenzliste
    full = (await client.get("/api/v1/screener", params={"limit": 100})).json()["items"]
    page = await client.get("/api/v1/screener", params={"limit": 3, "offset": 3})
    body = page.json()
    assert body["total"] == len(_SEED)            # total ignoriert das Fenster
    assert body["limit"] == 3 and body["offset"] == 3
    assert len(body["items"]) == 3
    # Fenster == Slice der Referenzliste -> deterministisches, DB-seitiges Paging
    assert [r["ticker"] for r in body["items"]] == [r["ticker"] for r in full[3:6]]


async def test_combined_filter_sort_page(app_and_db):
    client, _ = app_and_db
    r = await client.get("/api/v1/screener", params={
        "strategy": "WACHSTUM", "sort_by": "wlafar", "sort_dir": "desc",
        "limit": 2, "offset": 0})
    body = r.json()
    assert body["total"] == sum(1 for s in _SEED if s[4] == "WACHSTUM")
    wlafars = [row["wlafar"] for row in body["items"]]
    assert wlafars == sorted(wlafars, reverse=True)
    assert len(body["items"]) == 2


async def test_detail_endpoint_drivers_and_zones(app_and_db):
    client, _ = app_and_db
    r = await client.get("/api/v1/screener/nvda")   # case-insensitive
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "NVDA"
    assert body["targets"]["crv"] is not None
    assert body["drivers"]["bull"][0]["code"] == "trend_up"
    assert body["drivers"]["zones"][0]["is_entry"] is True
    assert "Fibonacci" in body["drivers"]["zones"][0]["categories"]


async def test_detail_404(app_and_db):
    client, _ = app_and_db
    r = await client.get("/api/v1/screener/NOPE")
    assert r.status_code == 404


async def test_query_pushes_order_limit_offset_to_sql(app_and_db):
    """Beweis des Push-down: das kompilierte SELECT enthält ORDER BY/LIMIT/OFFSET."""
    from sqlalchemy import nulls_last, select
    from api.queries import SORTABLE

    base = select(ScreenerRowModel).where(ScreenerRowModel.strategy_tag == "WACHSTUM")
    stmt = (base.order_by(nulls_last(SORTABLE["wlatar"].desc()),
                          ScreenerRowModel.ticker.asc())
            .limit(2).offset(1))
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True})).upper()
    assert "WHERE" in sql and "ORDER BY" in sql and "LIMIT" in sql and "OFFSET" in sql

    # Und die Helper-Funktion liefert konsistent (rows, total):
    _, sessionmaker = app_and_db[0], app_and_db[1]
    async with sessionmaker() as s:
        rows, total = await query_screener_rows(
            s, ScreenerFilters(strategy="WACHSTUM"), sort_by="wlatar", limit=2, offset=1)
    assert total == sum(1 for x in _SEED if x[4] == "WACHSTUM")
    assert len(rows) == 2


# =========================================================================== #
#  Block 4: End-to-End Kronos-Forecast — Worker-Chain, Retry, atomarer Upsert
# =========================================================================== #
import math                                                        # noqa: E402
from datetime import date, timedelta                               # noqa: E402

HORIZON = 30


def make_kronos_forecast(start_price: float, horizon: int = HORIZON) -> dict:
    """Simulierte 30-Tage-Inferenz: driftender Mittelpfad + sich weitende Bänder.

    Die Bandbreite wächst mit sqrt(t) (akkumulierende Unsicherheit) — der Kanal
    weitet sich also visuell mit dem Horizont, exakt wie echte Kronos-Ausgaben.
    """
    d0 = date(2026, 1, 2)
    mean_path, upper_band, lower_band, timestamps = [], [], [], []
    for i in range(horizon):
        m = start_price * (1.0 + 0.004 * i)                 # +0.4 %/Tag Drift
        half = start_price * 0.012 * math.sqrt(i + 1)       # weitendes Intervall
        mean_path.append(round(m, 4))
        upper_band.append(round(m + half, 4))
        lower_band.append(round(m - half, 4))
        timestamps.append((d0 + timedelta(days=i)).isoformat())
    return {"timestamps": timestamps, "mean_path": mean_path,
            "upper_band": upper_band, "lower_band": lower_band, "direction": "up"}


def build_snapshot(ticker: str, price: float = 100.0) -> MarketSnapshot:
    """Verarbeitbares Instrument: volle Technicals + Fundamentals + Kerzen."""
    candles: list[Candle] = []
    p = price * 0.7
    for i in range(140):
        p *= 1.0 + (0.004 if i % 5 else -0.006)             # leichter Aufwärtstrend
        candles.append(Candle(o=p * 0.99, h=p * 1.015, l=p * 0.985, c=p, v=1_000_000 + i * 5_000))
    technicals = dict(
        close=price, atr=price * 0.03,
        ema_50=price * 0.97, ema_200=price * 0.9,
        ema_50_slope=0.5, ema_200_slope=0.3,
        sma_200=price * 0.91, rsi=58.0, volume_ratio=1.6, roc=8.0,
    )
    fundamentals = dict(
        revenue_growth=0.22, eps_growth=0.18, fcf_margin=0.16, free_cash_flow=5.0e8,
        dividend_yield=0.012, roic=0.18, net_margin=0.21, debt_to_equity=0.4,
        pe=28.0, ev_ebitda=18.0, p_fcf=22.0, p_b=6.0,
    )
    return MarketSnapshot(
        instrument_id=ticker, ticker=ticker, asset_class="stock",
        sector="Technology", industry="Semiconductors", market_cap=8.0e9,
        currency="USD", price=price, technicals=technicals, fundamentals=fundamentals,
        candles=candles, distribution_days=1, avg_dollar_volume=5.0e8, recent_breakout=True)


class FakeKronos:
    """Liefert eine deterministische 30-Tage-Inferenz (warmes Modell-Stub)."""
    def __init__(self) -> None:
        self.calls = 0

    async def forecast(self, snap: MarketSnapshot, *, horizon: int) -> dict:
        self.calls += 1
        return make_kronos_forecast(snap.price, horizon)


class DeadKronos(FakeKronos):
    """Schlägt dauerhaft fehl (z. B. GPU offline)."""
    async def forecast(self, snap: MarketSnapshot, *, horizon: int) -> dict:
        self.calls += 1
        raise ConnectionError("Kronos-Backend nicht erreichbar")


@pytest_asyncio.fixture
async def fresh_db():
    tmp = tempfile.TemporaryDirectory()
    url = f"sqlite+aiosqlite:///{Path(tmp.name) / 'fc.db'}"
    engine = create_engine(url)
    await init_models(engine)
    sm = create_session_factory(engine)
    yield url, engine, sm
    await engine.dispose()
    tmp.cleanup()


async def test_batch_chain_persists_wellformed_forecast_history(fresh_db):
    """Volle Kette der Batch-Pipeline (compute_scores.py-Äquivalent):
    apply_forecasts -> run_screener_pipeline -> API-Auslieferung.

    Ersetzt den früheren arq-Worker-Kettentest (forecast_snapshots/
    compute_and_persist) — der arq-Worker wurde als Live-Prozess entfernt und
    durch das Batch-Skript ersetzt; dieser Test prüft jetzt exakt den Pfad, den
    compute_scores.py tatsächlich in Produktion durchläuft.
    """
    from infrastructure.forecast import apply_forecasts

    url, engine, sm = fresh_db
    ticker = "KRNS"
    snaps = {ticker: build_snapshot(ticker, price=120.0)}

    # 1) Forecast anheften (fehlerisoliert, wie in compute_scores.py)
    fk = FakeKronos()
    ok = await apply_forecasts(fk, snaps, horizon=HORIZON)
    assert ok == 1
    assert len(snaps[ticker].forecast["mean_path"]) == HORIZON

    # 2) Pipeline + atomarer Write-Back (ein commit) — direkt, kein Worker-Wrapper
    repo = ScreenerRepository(engine)
    async with sm() as session:
        res = await run_screener_pipeline(list(snaps), session, repository=repo,
                                          snapshots=snaps, commit=True)
    assert res.processed == 1, f"Pipeline-Fehler: {res.errors}"

    # 3) Auslieferung über den FastAPI-TestClient
    app = create_app(url)
    app.state.db_engine, app.state.sessionmaker = engine, sm
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        r = await c.get(f"/api/v1/screener/{ticker}")
        assert r.status_code == 200
        hist = r.json()["forecast_history"]

    # Wohlgeformt & vollständig
    assert len(hist) == HORIZON
    keys = {"timestamp", "mean", "upper", "lower"}
    assert all(keys <= set(p) for p in hist)
    assert all(isinstance(p["mean"], (int, float)) for p in hist)
    # Bänder konsistent: lower <= mean <= upper
    assert all(p["lower"] <= p["mean"] <= p["upper"] for p in hist)
    # Zeitstempel streng monoton (chronologisch ausgeliefert)
    ts = [p["timestamp"] for p in hist]
    assert ts == sorted(ts) and len(set(ts)) == HORIZON
    # Kanal weitet sich über den Horizont (Unsicherheit wächst)
    assert (hist[-1]["upper"] - hist[-1]["lower"]) > (hist[0]["upper"] - hist[0]["lower"])


async def test_forecast_permanent_failure_degrades_without_blocking(fresh_db):
    """Ein dauerhaft fallender Forecaster blockiert die Kette nie — Snapshot ohne Forecast.

    Ersetzt den früheren arq-Retry-Test: apply_forecasts() (compute_scores.py-Pfad)
    hat KEIN Retry/Backoff mehr (das war arq-Worker-/Kronos-GPU-spezifisch und
    entfällt mit dem torch-freien StatisticalForecaster, der deterministisch und
    praktisch nie transient fehlschlägt) — aber die Fehlerisolierung pro Ticker
    bleibt: ein permanent scheiternder Forecast darf den Lauf nie killen.
    """
    from infrastructure.forecast import apply_forecasts

    url, engine, sm = fresh_db
    dead = DeadKronos()
    snaps = {"DEAD": build_snapshot("DEAD")}

    ok = await apply_forecasts(dead, snaps, horizon=HORIZON)
    assert ok == 0
    assert dead.calls == 1                                   # kein Retry -> genau 1 Versuch
    assert snaps["DEAD"].forecast is None

    # Pipeline läuft trotzdem durch; forecast_history ist dann leer
    repo = ScreenerRepository(engine)
    async with sm() as session:
        res = await run_screener_pipeline(list(snaps), session, repository=repo,
                                          snapshots=snaps, commit=True)
    assert res.processed == 1

    app = create_app(url)
    app.state.db_engine, app.state.sessionmaker = engine, sm
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        r = await c.get("/api/v1/screener/DEAD")
        assert r.status_code == 200
        assert r.json()["forecast_history"] == []


# =========================================================================== #
#  Härtung: Fehlerisolierung (Ingest/Provider), Indikatoren, Health, CORS
# =========================================================================== #
async def test_fmp_fetch_returns_none_on_terminal_4xx():
    """Unbekannter Ticker (404 auf allen Endpoints) -> sauberes None, kein Crash."""
    from infrastructure.providers.fmp import FMPMarketDataProvider

    def h404(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json=[])

    prov = FMPMarketDataProvider(api_key="TESTKEY")
    await prov._client.aclose()
    prov._client = httpx.AsyncClient(base_url=prov.base_url, transport=httpx.MockTransport(h404))
    snap = await prov.fetch("NOPE")
    await prov.aclose()
    assert snap is None


async def test_indicators_short_series_no_crash():
    """Kurze Kerzenreihe: keine Exception, nur verfügbare Felder."""
    from infrastructure.providers.indicators import technicals_from_candles
    candles = [Candle(o=10, h=11, l=9, c=10 + i, v=1000) for i in range(3)]
    t = technicals_from_candles(candles, price=12.0)
    assert t["close"] == 12.0
    assert "ema_200" not in t and "rsi" not in t   # zu wenig Daten -> weggelassen


async def test_health_reports_db_ok(app_and_db):
    client, _ = app_and_db
    body = (await client.get("/health")).json()
    assert body["status"] == "ok" and body["db"] == "ok"


async def test_cors_header_present(app_and_db):
    client, _ = app_and_db
    r = await client.get("/api/v1/screener",
                         headers={"Origin": "http://localhost:3000"}, params={"limit": 1})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


async def test_search_and_metadata_filters(app_and_db):
    client, _ = app_and_db
    # Volltext-Suche über Name/Ticker
    r = await client.get("/api/v1/screener", params={"search": "NVDA"})
    body = r.json()
    assert body["total"] == 1 and body["items"][0]["ticker"] == "NVDA"
    assert body["items"][0]["name"] == "NVDA Inc."
    assert body["items"][0]["rating"] in {"STARK KAUFEN", "KAUFEN", "HALTEN",
                                          "REDUZIEREN", "VERKAUFEN"}
    # Branchenfilter
    sec = _SECTORS[0]
    b2 = (await client.get("/api/v1/screener", params={"sector": sec, "limit": 100})).json()
    assert {row["sector"] for row in b2["items"]} == {sec}


async def test_min_score_and_max_risk_filters(app_and_db):
    client, _ = app_and_db
    b = (await client.get("/api/v1/screener",
                          params={"min_total_score": 80, "limit": 100})).json()
    assert all(row["total_score"] >= 80 for row in b["items"])
    # höchstens "mittel" (Level 3) -> keine hoch/sehr hoch
    b2 = (await client.get("/api/v1/screener",
                           params={"max_risk_level": 3, "limit": 100})).json()
    assert all(row["risikoklasse"] in {"sehr niedrig", "niedrig", "mittel"}
               for row in b2["items"])


async def test_facets_endpoint(app_and_db):
    client, _ = app_and_db
    f = (await client.get("/api/v1/screener/facets")).json()
    assert f["total"] == len(_SEED)
    assert set(_SECTORS) <= set(f["sectors"])
    assert "WACHSTUM" in f["strategies"] and "CASHFLOW" in f["strategies"]
    assert "facets" not in f["sectors"]              # /facets nicht als Ticker missgedeutet


async def test_tickers_filter_for_favorites(app_and_db):
    client, _ = app_and_db
    r = await client.get("/api/v1/screener", params={"tickers": "nvda,msft", "limit": 100})
    body = r.json()
    assert body["total"] == 2
    assert {row["ticker"] for row in body["items"]} == {"NVDA", "MSFT"}


async def test_summary_breadth(app_and_db):
    client, _ = app_and_db
    s = (await client.get("/api/v1/screener/summary")).json()
    assert s["total"] == len(_SEED)
    assert sum(s["by_rating"].values()) == len(_SEED)        # jede Zeile genau ein Rating
    assert s["avg_total_score"] is not None
    # gefiltert konsistent mit der Liste
    f = (await client.get("/api/v1/screener/summary", params={"strategy": "WACHSTUM"})).json()
    assert f["total"] == sum(1 for x in _SEED if x[4] == "WACHSTUM")


async def test_news_without_provider_returns_note(app_and_db):
    client, _ = app_and_db          # kein FMP_API_KEY in der Testumgebung
    r = await client.get("/api/v1/screener/NVDA/news")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "NVDA" and body["items"] == []
    assert "FMP_API_KEY" in (body["note"] or "")
    # Unbekannter Ticker -> 404
    assert (await client.get("/api/v1/screener/NOPE/news")).status_code == 404


async def test_batched_helper():
    from infrastructure.batching import batched
    assert batched([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
    assert batched([], 50) == []
    assert batched([1, 2, 3], 0) == [[1], [2], [3]]   # n<1 -> Größe 1


# ---- Real-World Ingest (seed_real_universe) -------------------------------
class _FakeRealProvider:
    """Simuliert die FMP-Index-/Profil-Calls ohne Netz."""
    async def fetch_constituents(self, index: str):
        if index == "sp500":
            return [{"symbol": "AAPL", "name": "Apple Inc.", "sector": "Technology"},
                    {"symbol": "MSFT", "name": "Microsoft Corp.", "sector": "Technology"}]
        return [{"symbol": "NVDA", "name": "NVIDIA Corp.", "sector": "Technology"}]

    async def fetch_profile_meta(self, ticker: str):
        return {"name": f"{ticker} (real)", "sector": "Technology", "country": "USA",
                "currency": "USD", "price": 123.45, "dividend_yield": 0.012,
                "asset_class": "Aktie"}


async def test_seed_real_universe_writes_metadata(fresh_db):
    from scripts.seed_real_universe import seed_real_universe
    url, engine, sm = fresh_db
    repo = ScreenerRepository(engine)

    n = await seed_real_universe(_FakeRealProvider(), repo, sm,
                                 indices=("sp500", "nasdaq"))
    assert n == 3                                  # AAPL, MSFT, NVDA

    app = create_app(url)
    app.state.db_engine, app.state.sessionmaker = engine, sm
    app.state.news_provider, app.state.news_cache = None, TTLCache()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        body = (await c.get("/api/v1/screener", params={"limit": 100})).json()
        assert body["total"] == 3
        aapl = next(r for r in body["items"] if r["ticker"] == "AAPL")
        assert aapl["name"] == "AAPL (real)" and aapl["country"] == "USA"
        assert aapl["sector"] == "Technology" and aapl["asset_class"] == "Aktie"
        assert abs(aapl["dividend_yield"] - 0.012) < 1e-9
        # JSON-NOT-NULL-Spalten haben beim INSERT ihre Defaults bekommen:
        assert aapl["strategy_tags"] == [] and aapl["targets"]["crv"] is None


class _CountingNews:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch_news(self, ticker: str, *, limit: int):
        self.calls += 1
        return [{"title": f"{ticker} Schlagzeile #{self.calls}", "url": "http://x",
                 "source": "Wire", "published_at": "2026-01-01", "snippet": "…", "image": None}]


async def test_news_endpoint_caches(fresh_db):
    from api.cache import TTLCache as _TTL
    url, engine, sm = fresh_db
    async with sm() as s:
        s.add(ScreenerRowModel(ticker="NVDA"))     # JSON-Defaults füllen sich beim Flush
        await s.commit()

    app = create_app(url)
    app.state.db_engine, app.state.sessionmaker = engine, sm
    counting = _CountingNews()
    app.state.news_provider, app.state.news_cache = counting, _TTL(300)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        a = (await c.get("/api/v1/screener/NVDA/news")).json()
        b = (await c.get("/api/v1/screener/NVDA/news")).json()    # zweiter Abruf -> Cache
    assert counting.calls == 1                      # FMP nur EINMAL angefragt
    assert a["items"][0]["title"] == b["items"][0]["title"]
    assert a["items"][0]["title"].endswith("#1")


# ---- Yahoo-Provider (gratis, gemockt — kein Netz) -------------------------
class _FakeYfTicker:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    def history(self, period: str, interval: str, auto_adjust: bool):
        import pandas as pd
        n = 210
        base = [100.0 + i * 0.2 for i in range(n)]
        return pd.DataFrame({
            "Open": base, "High": [b + 1 for b in base],
            "Low": [b - 1 for b in base], "Close": [b + 0.5 for b in base],
            "Volume": [1_000_000 + i for i in range(n)],
        })

    def get_info(self):
        return {"longName": "Fake Co.", "sector": "Technology", "country": "USA",
                "currency": "USD", "currentPrice": 142.0, "marketCap": 1.0e10,
                "trailingAnnualDividendYield": 0.021, "profitMargins": 0.20,
                "returnOnEquity": 0.18, "debtToEquity": 55.0, "revenueGrowth": 0.15,
                "trailingPE": 25.0, "priceToBook": 5.0, "enterpriseToEbitda": 15.0,
                "freeCashflow": 5.0e8, "totalRevenue": 2.0e9, "quoteType": "EQUITY",
                "averageVolume": 2_000_000}

    @property
    def news(self):
        return [{"content": {"title": "Fake Schlagzeile",
                             "canonicalUrl": {"url": "http://x"},
                             "provider": {"displayName": "Wire"},
                             "pubDate": "2026-01-01", "summary": "Zusammenfassung"}}]


async def test_yahoo_provider_builds_snapshot(monkeypatch):
    import yfinance
    monkeypatch.setattr(yfinance, "Ticker", _FakeYfTicker)
    from infrastructure.providers import YahooMarketDataProvider

    prov = YahooMarketDataProvider(period="1y", max_concurrency=4)
    snap = await prov.fetch("FAKE")
    await prov.aclose()
    assert snap is not None
    assert snap.name == "Fake Co." and snap.sector == "Technology"
    assert snap.country == "USA" and snap.asset_class == "Aktie"
    assert len(snap.candles) == 210
    assert snap.technicals.get("ema_200") and snap.technicals.get("rsi")
    # Fundamentaldaten korrekt gemappt (inkl. fcf_margin/p_fcf abgeleitet)
    assert abs(snap.fundamentals["dividend_yield"] - 0.021) < 1e-9
    assert abs(snap.fundamentals["debt_to_equity"] - 0.55) < 1e-9   # 55 % -> 0.55
    assert abs(snap.fundamentals["fcf_margin"] - 0.25) < 1e-9       # 5e8 / 2e9

    news = await prov.fetch_news("FAKE", limit=5)
    assert news[0]["title"] == "Fake Schlagzeile" and news[0]["source"] == "Wire"


async def test_build_universe_dedup_and_limit(monkeypatch):
    from infrastructure.providers import universe as U

    async def fake_sp500(client):
        return [{"symbol": "AAPL", "name": "Apple Inc.", "sector": "Information Technology"},
                {"symbol": "MSFT", "name": "Microsoft Corp.", "sector": "Information Technology"}]

    async def fake_listing(client, url):
        return ["AAPL", "TSLA", "AMD"]               # AAPL überschneidet sich -> Dedup

    monkeypatch.setattr(U, "_fetch_sp500", fake_sp500)
    monkeypatch.setattr(U, "_fetch_listing", fake_listing)

    uni = await U.build_universe(limit=4, source="broad")
    syms = [d["symbol"] for d in uni]
    assert syms[:2] == ["AAPL", "MSFT"]              # S&P 500 zuerst (mit Metadaten)
    assert len(syms) == len(set(syms)) == 4          # dedupliziert, auf limit gekappt
    assert "TSLA" in syms and uni[0]["name"] == "Apple Inc."

    # Yahoo-Symbolnormalisierung
    assert U._yahoo_symbol("BRK.B") == "BRK-B"


# ---- Forecast-Band (statistisch, ohne torch) ------------------------------
async def test_statistical_forecaster_band():
    from infrastructure.forecast import StatisticalForecaster
    snap = build_snapshot("FOO", price=100.0)
    fc = await StatisticalForecaster(horizon=30).forecast(snap)
    assert fc["method"] == "statistical"
    assert len(fc["mean_path"]) == len(fc["upper_band"]) == len(fc["lower_band"]) == 30
    assert all(lo <= m <= up for lo, m, up
               in zip(fc["lower_band"], fc["mean_path"], fc["upper_band"]))
    # Band weitet sich mit dem Horizont (√t · echte Vola)
    w0 = fc["upper_band"][0] - fc["lower_band"][0]
    wN = fc["upper_band"][-1] - fc["lower_band"][-1]
    assert wN > w0


async def test_forecaster_factory_default_is_statistical():
    from infrastructure.forecast import build_forecaster, StatisticalForecaster
    assert isinstance(build_forecaster(), StatisticalForecaster)
    assert isinstance(build_forecaster("statistical"), StatisticalForecaster)


async def test_pipeline_persists_price_history_and_forecast(fresh_db):
    from infrastructure.forecast import StatisticalForecaster
    url, engine, sm = fresh_db
    snap = build_snapshot("PHX", price=120.0)
    snap.forecast = await StatisticalForecaster(horizon=30).forecast(snap)
    repo = ScreenerRepository(engine)
    async with sm() as session:
        res = await run_screener_pipeline(["PHX"], session, repository=repo,
                                          snapshots={"PHX": snap}, commit=True)
    assert res.processed == 1

    app = create_app(url)
    app.state.db_engine, app.state.sessionmaker = engine, sm
    app.state.news_provider, app.state.news_cache = None, TTLCache()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        d = (await c.get("/api/v1/screener/PHX")).json()
    assert len(d["price_history"]) > 50              # echte Kerzen -> Verlauf
    assert len(d["forecast_history"]) == 30
    assert d["targets"]["forecast_return"] is not None
    assert d["targets"]["forecast_method"] == "statistical"


# ---- Rotierender Sync: älteste zuerst + data_as_of -------------------------
async def test_rotation_selects_oldest_first():
    from scripts.rotating_sync import _select_oldest

    class _S:
        def __init__(self, as_of):
            self.as_of = as_of

    universe = ["A", "B", "C", "D"]
    cache = {"A": _S("2026-06-01"), "B": _S("2026-06-03"), "C": _S("2026-06-02")}  # D nie
    picked = _select_oldest(universe, cache, 2)
    assert picked[0] == "D"        # nie beschafft -> ganz vorne
    assert picked[1] == "A"        # dann der älteste Stand


async def test_data_as_of_persists_and_serves(fresh_db):
    url, engine, sm = fresh_db
    snap = build_snapshot("ASOF", price=50.0)
    snap.as_of = "2026-06-10T08:00:00+00:00"
    repo = ScreenerRepository(engine)
    async with sm() as session:
        res = await run_screener_pipeline(["ASOF"], session, repository=repo,
                                          snapshots={"ASOF": snap}, commit=True)
    assert res.processed == 1

    app = create_app(url)
    app.state.db_engine, app.state.sessionmaker = engine, sm
    app.state.news_provider, app.state.news_cache = None, TTLCache()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        detail = (await c.get("/api/v1/screener/ASOF")).json()
        lst = (await c.get("/api/v1/screener", params={"search": "ASOF"})).json()
    assert detail["data_as_of"] == "2026-06-10T08:00:00+00:00"
    assert lst["items"][0]["data_as_of"] == "2026-06-10T08:00:00+00:00"


# --------------------------------------------------------------------------- #
#  Standalone-Runner (ohne pytest)
# --------------------------------------------------------------------------- #
async def _main() -> None:
    tmp = tempfile.TemporaryDirectory()
    url = f"sqlite+aiosqlite:///{Path(tmp.name) / 'screener.db'}"
    engine = create_engine(url)
    await init_models(engine)
    sm = create_session_factory(engine)
    await _seed(sm)
    app = create_app(url)
    app.state.db_engine, app.state.sessionmaker = engine, sm
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        r = await c.get("/api/v1/screener", params={"limit": 5})
        b = r.json()
        print(f"total={b['total']} top5={[ (x['ticker'], x['wlatar']) for x in b['items'] ]}")
        d = (await c.get("/api/v1/screener/MSFT")).json()
        print(f"detail MSFT: crv={d['targets']['crv']} zones={len(d['drivers']['zones'])} "
              f"bull={d['drivers']['bull'][0]['statement']}")
    await engine.dispose()
    tmp.cleanup()
    print("standalone smoke OK")


if __name__ == "__main__":
    asyncio.run(_main())
