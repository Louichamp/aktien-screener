"""Tests für die Ausbruchs-/Struktur-Module (V2.0).

Der Schwerpunkt liegt auf den Eigenschaften, die in der empirischen Messung
tatsächlich zählen — Segment-Gating und die korrekte Pivot-Definition —, nicht
auf kosmetischen Kennzahlen.
"""
from __future__ import annotations

import pytest

from screener.base_formation import BaseState, detect_base
from screener.breakout_signal import (MAX_DOLLAR_VOLUME, MIN_DOLLAR_VOLUME,
                                      evaluate_breakout)
from screener.zones import Candle


def _series(closes: list[float], *, volume: float = 100_000.0,
            spread: float = 0.01) -> list[Candle]:
    """Kerzenreihe aus Schlusskursen; Hoch/Tief symmetrisch um den Schluss."""
    return [Candle(c, c * (1 + spread), c * (1 - spread), c, volume) for c in closes]


# --------------------------------------------------------------------------- #
#  breakout_signal — Segment-Gating
# --------------------------------------------------------------------------- #
def test_zu_wenig_historie_gibt_none():
    assert evaluate_breakout(_series([10.0] * 20), price=10.0) is None


def test_illiquide_werte_werden_nicht_gemeldet():
    # 1000 Stück × 10 $ = 10.000 $ Tagesumsatz — weit unter der Schwelle.
    candles = _series([10.0] * 70, volume=1_000.0)
    sig = evaluate_breakout(candles, price=99.0)
    assert sig is not None and not sig.applicable and not sig.triggered
    assert sig.dollar_volume < MIN_DOLLAR_VOLUME


def test_penny_werte_werden_ausgeschlossen():
    candles = _series([2.0] * 70, volume=5_000_000.0)
    sig = evaluate_breakout(candles, price=2.5)
    assert sig is not None and not sig.applicable


def test_hochliquide_werte_bekommen_kein_ausbruchssignal():
    """Über 20 Mio $ Tagesumsatz wurde KEIN Vorteil gemessen — dort darf das
    Signal auch dann nicht feuern, wenn der Kurs technisch ausbricht."""
    candles = _series([100.0] * 70, volume=1_000_000.0)   # 100 $ × 1 Mio = 100 Mio $
    sig = evaluate_breakout(candles, price=200.0)
    assert sig is not None
    assert sig.dollar_volume > MAX_DOLLAR_VOLUME
    assert not sig.applicable and not sig.triggered


def test_ausbruch_im_gemessenen_segment_feuert():
    # 10 $ × 500.000 = 5 Mio $ Tagesumsatz -> mittleres Segment.
    candles = _series([10.0] * 70, volume=500_000.0)
    level = max(c.h for c in candles[-61:-1])
    sig = evaluate_breakout(candles, price=level * 1.02)
    assert sig is not None and sig.applicable and sig.triggered
    assert sig.breakout_level == pytest.approx(level, rel=1e-6)


def test_bereits_darueber_ist_kein_frischer_ausbruch():
    """Ein Titel, der seit Wochen über dem Niveau notiert, darf nicht jeden Tag
    erneut als Ausbruch gemeldet werden."""
    closes = [10.0] * 60 + [12.0] * 10          # Vortagesschluss liegt schon oben
    candles = _series(closes, volume=500_000.0)
    sig = evaluate_breakout(candles, price=12.1)
    assert sig is not None and sig.applicable
    assert not sig.triggered


# --------------------------------------------------------------------------- #
#  base_formation — Level-Ableitung
# --------------------------------------------------------------------------- #
def test_kurze_historie_gibt_none():
    assert detect_base(_series([10.0] * 10), price=10.0, atr=0.2) is None


def test_pivot_enthaelt_die_letzte_kerze_nicht():
    """Regression: Wurde der Pivot aus der Historie INKLUSIVE der letzten Kerze
    gebildet, enthielt er deren Hoch — und da ein Schlusskurs nie über dem
    eigenen Tageshoch liegt, war ein Ausbruch über den eigenen Pivot
    rechnerisch unmöglich. `BREAKOUT` war damit unerreichbar."""
    # Maßvoller Ausbruch (0,5 ATR über dem Pivot) — ein größerer Satz wäre
    # zu Recht EXTENDED und würde die eigentliche Aussage verdecken.
    closes = [10.0] * 60 + [10.2]               # letzte Kerze macht ein neues Hoch
    candles = _series(closes)
    b = detect_base(candles, price=10.2, atr=0.2)
    assert b is not None
    prior_high = max(c.h for c in candles[:-1])
    assert b.pivot == pytest.approx(prior_high, rel=1e-6)
    assert b.pivot < 10.2
    assert b.state == BaseState.BREAKOUT


def test_kurs_unter_basistief_ist_gebrochen():
    closes = [10.0] * 60 + [6.0]
    b = detect_base(_series(closes), price=6.0, atr=0.2)
    assert b is not None and b.state == BaseState.FAILED


def test_level_sind_konsistent_geordnet():
    closes = [10.0 + (i % 7) * 0.1 for i in range(80)]
    b = detect_base(_series(closes), price=closes[-1], atr=0.15)
    assert b is not None
    assert b.stop_suggest < b.buy_zone_low <= b.buy_zone_high
    assert b.invalidation == b.base_low
    assert 0.0 <= b.risk_pct <= 1.0


def test_keine_qualitaetsbewertung_mehr():
    """Die Qualitätsbewertung wurde gemessen (Korrelation zur Rendite −0,061)
    und entfernt. Wer sie wieder einführt, soll hier stolpern und sie vorher
    mit scripts/backtest_base.py neu messen."""
    b = detect_base(_series([10.0 + (i % 5) * 0.2 for i in range(80)]),
                    price=10.4, atr=0.2)
    assert b is not None
    assert not hasattr(b, "quality")
