"""Ende-zu-Ende-Test der Pipeline gegen eine echte Datenbank (SQLite).

Bisher gab es KEINEN Test, der den kompletten Weg
Snapshot -> ScoreEngine -> Zonen/Level -> Status -> Write-Back -> API
durchläuft. Genau dort sind in diesem Projekt die teuren Fehler passiert
(abgeschnittene Namen, die den ganzen Lauf killten; Felder, die nie in der
Datenbank ankamen). Der Test deckt die Naht ab, nicht die Einzelteile.
"""
from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from infrastructure.database.config import (create_engine, create_session_factory,
                                            init_models)
from infrastructure.database.repository import ScreenerRepository
from infrastructure.providers.indicators import technicals_from_candles
from screener.pipeline import MarketSnapshot, run_screener_pipeline
from screener.zones import Candle


def _synth(n: int = 320, start: float = 50.0, drift: float = 0.0015) -> list[Candle]:
    """Aufwärtstrend mit Schwankung — deterministisch, ohne Netzzugriff."""
    out, px = [], start
    for i in range(n):
        px *= (1.0 + drift + 0.02 * math.sin(i / 7.0))
        hi, lo = px * 1.012, px * 0.988
        vol = 900_000 + 120_000 * math.sin(i / 3.0)
        out.append(Candle(px * 0.998, hi, lo, px, vol))
    return out


def _snapshot(ticker: str, candles: list[Candle], **kw) -> MarketSnapshot:
    price = candles[-1].c
    return MarketSnapshot(
        instrument_id=ticker, ticker=ticker, name=f"{ticker} Inc.",
        sector="Technology", country="USA", asset_class="Aktie",
        price=price, currency="USD", as_of="2026-09-06T00:00:00+00:00",
        technicals=technicals_from_candles(candles, price=price),
        fundamentals={"net_margin": 0.21, "roic": 0.18, "revenue_growth": 0.14,
                      "pe": 22.0, "dividend_yield": 0.011},
        candles=candles, market_cap=5.0e9, avg_dollar_volume=8.0e6, **kw)


@pytest_asyncio.fixture
async def db():
    tmp = tempfile.TemporaryDirectory()
    engine = create_engine(f"sqlite+aiosqlite:///{Path(tmp.name) / 'e2e.db'}")
    await init_models(engine)
    yield engine, create_session_factory(engine), ScreenerRepository(engine)
    await engine.dispose()
    tmp.cleanup()


@pytest.mark.asyncio
async def test_pipeline_schreibt_vollstaendige_zeile(db):
    engine, sm, repo = db
    snaps = {t: _snapshot(t, _synth(320, 40 + i * 15))
             for i, t in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE",
                                    "FFF", "GGG", "HHH", "III", "JJJ"])}
    async with sm() as s:
        res = await run_screener_pipeline(list(snaps), s, repository=repo,
                                          snapshots=snaps, commit=True)
    assert res.processed == len(snaps), res.errors
    assert res.failed == 0, res.errors

    async with sm() as s:
        row = await repo.get_screener_row(s, "AAA")
    assert row is not None
    assert row.total_score is not None and 0 <= row.total_score <= 100
    assert row.rating
    # Die neuen Felder muessen tatsaechlich in der DB ankommen — genau das
    # ging vorher verloren (Sub-Scores wurden berechnet und verworfen).
    assert row.score_breakdown, "score_breakdown wurde nicht geschrieben"
    assert row.score_breakdown["technical"], "keine technischen Faktoren"
    assert row.signal_strength, "signal_strength wurde nicht geschrieben"


@pytest.mark.asyncio
async def test_aufschluesselung_erklaert_den_gesamtscore(db):
    """Die Beitraege muessen den ausgewiesenen Score tatsaechlich ergeben —
    sonst ist die 'Warum 87?'-Anzeige eine huebsche Luege."""
    engine, sm, repo = db
    snaps = {t: _snapshot(t, _synth(320, 30 + i * 20))
             for i, t in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE",
                                    "FFF", "GGG", "HHH", "III", "JJJ"])}
    async with sm() as s:
        await run_screener_pipeline(list(snaps), s, repository=repo,
                                    snapshots=snaps, commit=True)
        row = await repo.get_screener_row(s, "BBB")

    tech = [c for c in row.score_breakdown["technical"] if c["available"]]
    assert tech
    summe = sum(c["contribution"] for c in tech)
    abdeckung = sum(c["weight"] for c in tech)
    # contribution ist auf das VOLLE Gewicht bezogen; bei Teilabdeckung
    # renormiert die Engine -> Vergleich entsprechend hochrechnen.
    assert abs(summe / abdeckung - row.wlatar * 10) < 6.0, (
        f"Aufschluesselung {summe/abdeckung:.1f} passt nicht zu WLATAR {row.wlatar*10}")


@pytest.mark.asyncio
async def test_ein_kaputter_ticker_killt_den_lauf_nicht(db):
    """Robustheit: Ein Datensatz mit unbrauchbaren Werten darf die anderen
    nicht mitreissen."""
    engine, sm, repo = db
    snaps = {t: _snapshot(t, _synth(320, 40 + i * 15))
             for i, t in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE",
                                    "FFF", "GGG", "HHH", "III", "JJJ"])}
    kaputt = _snapshot("BAD", _synth(320, 55.0))
    kaputt.technicals = {"close": float("nan"), "atr": 0.0}
    kaputt.candles = []
    kaputt.price = 0.0
    snaps["BAD"] = kaputt

    async with sm() as s:
        res = await run_screener_pipeline(list(snaps), s, repository=repo,
                                          snapshots=snaps, commit=True)
    assert res.processed >= 10, f"gesunde Ticker verloren: {res.errors}"
    async with sm() as s:
        assert await repo.get_screener_row(s, "AAA") is not None


@pytest.mark.asyncio
async def test_ueberlanger_name_bricht_den_write_back_nicht(db):
    """Regression: Ein 166-Zeichen-Name brach live drei Tage in Folge den
    kompletten Cron-Lauf (StringDataRightTruncationError)."""
    engine, sm, repo = db
    snaps = {t: _snapshot(t, _synth(320, 40 + i * 15))
             for i, t in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE",
                                    "FFF", "GGG", "HHH", "III", "JJJ"])}
    snaps["AAA"].name = "X" * 400

    async with sm() as s:
        res = await run_screener_pipeline(list(snaps), s, repository=repo,
                                          snapshots=snaps, commit=True)
    assert res.processed >= 9, res.errors
    async with sm() as s:
        assert await repo.get_screener_row(s, "BBB") is not None
