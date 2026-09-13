"""Audit der Band-Funktionen (§31) und Eigenschaftstests der Composites (§33).

`band(wert, stuetzpunkte)` bildet eine Kennzahl stueckweise linear auf 0..10 ab.
Geprueft wird fuer jede in Produktion verwendete Kurve:

  * Verhalten unter dem Minimum, am Minimum, in der Mitte, am Maximum und
    darueber (Klemmen statt Extrapolieren)
  * Monotonie dort, wo sie wirtschaftlich gelten MUSS
  * Lage der Sweet Spots bei bewusst nicht-monotonen Kurven
  * keine Spruenge (Stetigkeit)

Die Kurven sind Heuristiken. Dieser Test prueft NICHT, ob sie die Zukunft
vorhersagen — nur, ob sie das tun, was sie zu tun vorgeben.
"""
from __future__ import annotations

import math

import pytest

from scoring.normalization import band, clamp


# --------------------------------------------------------------------------- #
#  Grundverhalten von band()
# --------------------------------------------------------------------------- #
SKALA = [(0.0, 2.0), (0.10, 5.0), (0.20, 8.0), (0.35, 10.0)]


def test_unter_minimum_wird_geklemmt():
    assert band(-5.0, SKALA) == 2.0


def test_am_minimum():
    assert band(0.0, SKALA) == 2.0


def test_in_der_mitte_wird_linear_interpoliert():
    assert band(0.05, SKALA) == pytest.approx(3.5)


def test_am_maximum():
    assert band(0.35, SKALA) == 10.0


def test_ueber_maximum_wird_geklemmt():
    """Kein Extrapolieren: ein absurd hoher Wert darf den Score nicht sprengen."""
    assert band(1000.0, SKALA) == 10.0


def test_none_bleibt_none():
    assert band(None, SKALA) is None


def test_leere_skala_liefert_none():
    assert band(1.0, []) is None


def test_stuetzpunkte_muessen_nicht_sortiert_sein():
    assert band(0.05, list(reversed(SKALA))) == pytest.approx(3.5)


def test_stetig_keine_spruenge():
    """Ein Score darf bei minimaler Kennzahl-Aenderung nicht springen."""
    for x in [i / 200.0 for i in range(0, 80)]:
        a, b = band(x, SKALA), band(x + 1e-6, SKALA)
        assert abs(a - b) < 1e-3


def test_clamp_haelt_den_wertebereich():
    assert clamp(-3.0) == 0.0 and clamp(99.0) == 10.0 and clamp(5.0) == 5.0


# --------------------------------------------------------------------------- #
#  Die in Produktion verwendeten Kurven
# --------------------------------------------------------------------------- #
# (Name, Stuetzpunkte, monoton steigend?)  — Quelle: scoring/computors/*.py
MONOTON_STEIGEND = {
    "fund_quality.roic": [(0.0, 2), (0.08, 5), (0.15, 7), (0.25, 9), (0.4, 10)],
    "fund_quality.net_margin": [(0.0, 2), (0.1, 5), (0.2, 8), (0.35, 10)],
    "growth.rev_eps": [(0.0, 2), (0.05, 4), (0.15, 6), (0.25, 8), (0.5, 10)],
    "volume.up_vol_ratio": [(0.30, 1), (0.40, 3), (0.48, 5), (0.55, 8), (0.65, 10)],
    "inst_demand.up_vol_ratio": [(0.30, 1), (0.42, 3), (0.50, 6), (0.58, 9), (0.70, 10)],
    "volume.obv_slope": [(-1.0, 0), (-0.4, 2), (-0.1, 4), (0.0, 5), (0.1, 7),
                         (0.4, 9), (1.0, 10)],
    "inst_demand.obv_slope": [(-1.0, 0), (-0.3, 2), (0.0, 5), (0.3, 8), (0.7, 10)],
    "momentum.ratio": [(-1.5, 0), (-0.5, 3), (0.0, 5), (0.5, 7), (1.0, 8.5), (2.0, 10)],
    "momentum.ret_roh": [(-30, 1), (-10, 3), (0, 4), (10, 6), (30, 9), (60, 10)],
    "momentum.ret_3m": [(-25, 1), (-8, 3), (0, 4), (8, 6), (20, 9), (40, 10)],
    "kronos.expected_return": [(-0.30, 0), (-0.15, 2), (-0.05, 4), (0.0, 5),
                               (0.05, 6), (0.10, 7.5), (0.20, 9), (0.35, 10)],
}

MONOTON_FALLEND = {
    "fund_quality.debt_equity": [(0.0, 10), (1.0, 7), (2.0, 4), (3.0, 2)],
    "risk.debt_equity": [(0.0, 10), (1.0, 8), (2.0, 5), (3.0, 2)],
    "risk.atr_pct": [(0.01, 10), (0.02, 8), (0.03, 6), (0.05, 4), (0.08, 2), (0.12, 0)],
    "risk.downside_dev": [(0.10, 10), (0.15, 8), (0.22, 6), (0.32, 4), (0.45, 2),
                          (0.65, 0)],
    "risk.max_drawdown": [(0.05, 10), (0.10, 9), (0.20, 7), (0.35, 5), (0.50, 3),
                          (0.70, 1)],
    "inst_demand.distribution_days": [(0, 10), (2, 8), (3, 6), (5, 3), (7, 1)],
    "breakout.bb_width": [(0.02, 10), (0.04, 9), (0.07, 7), (0.12, 5), (0.18, 3),
                          (0.25, 1)],
    "breakout.chop": [(20, 10), (38, 8), (50, 5), (62, 2), (80, 0)],
}

# Bewusst nicht-monoton: (Name, Stuetzpunkte, Lage des Optimums)
SWEETSPOT = {
    "momentum.rsi": ([(30, 4), (50, 7), (60, 9), (70, 8), (80, 5), (90, 2)], 60),
    "breakout.rsi": ([(20, 4), (35, 7), (45, 9), (55, 10), (65, 8), (75, 5),
                      (85, 2)], 55),
    "setup.rsi": ([(10, 3), (30, 5), (40, 9), (50, 10), (60, 9), (70, 6), (80, 3),
                   (90, 1)], 50),
    "breakout.adx": ([(5, 2), (15, 5), (20, 8), (30, 10), (42, 8), (55, 5),
                      (70, 2)], 30),
    "volume.volume_ratio": ([(0.2, 2), (0.5, 4), (0.8, 6), (1.2, 8), (2.0, 9),
                             (4.0, 7)], 2.0),
    "setup.volume_ratio": ([(0.1, 9), (0.5, 10), (0.7, 9), (1.0, 7), (1.5, 5),
                            (2.5, 3), (4.0, 1)], 0.5),
    "setup.macd_hist_pct": ([(-2.0, 0), (-0.5, 2), (-0.1, 4), (0.0, 5), (0.1, 7),
                             (0.3, 9), (0.8, 10), (1.5, 8)], 0.8),
    "setup.bb_pct": ([(-0.10, 8), (0.0, 10), (0.20, 9), (0.40, 7), (0.60, 5),
                      (0.80, 3), (1.0, 2), (1.20, 1)], 0.0),
    "setup.stoch_k": ([(0, 7), (20, 9), (40, 8), (50, 7), (60, 6), (75, 4),
                       (85, 2), (100, 1)], 20),
}


def _abtasten(pts: list[tuple[float, float]], n: int = 200) -> list[float]:
    lo, hi = min(p[0] for p in pts), max(p[0] for p in pts)
    spanne = hi - lo
    return [band(lo + spanne * i / n, pts) for i in range(n + 1)]


@pytest.mark.parametrize("name", sorted(MONOTON_STEIGEND))
def test_steigende_kurven_sind_monoton(name: str):
    werte = _abtasten(MONOTON_STEIGEND[name])
    assert all(b >= a - 1e-9 for a, b in zip(werte, werte[1:])), \
        f"{name} ist nicht monoton steigend"


@pytest.mark.parametrize("name", sorted(MONOTON_FALLEND))
def test_fallende_kurven_sind_monoton(name: str):
    werte = _abtasten(MONOTON_FALLEND[name])
    assert all(b <= a + 1e-9 for a, b in zip(werte, werte[1:])), \
        f"{name} ist nicht monoton fallend"


@pytest.mark.parametrize("name", sorted(SWEETSPOT))
def test_sweetspot_liegt_wo_dokumentiert(name: str):
    pts, optimum = SWEETSPOT[name]
    bestwert = band(optimum, pts)
    lo, hi = min(p[0] for p in pts), max(p[0] for p in pts)
    for i in range(201):
        x = lo + (hi - lo) * i / 200
        assert band(x, pts) <= bestwert + 1e-9, \
            f"{name}: {x} schlaegt den dokumentierten Sweet Spot {optimum}"


@pytest.mark.parametrize("name,pts", sorted(
    [(k, v) for k, v in MONOTON_STEIGEND.items()]
    + [(k, v) for k, v in MONOTON_FALLEND.items()]
    + [(k, v[0]) for k, v in SWEETSPOT.items()]))
def test_alle_kurven_bleiben_im_wertebereich(name: str, pts):
    for x in (-1e9, min(p[0] for p in pts) - 1, 0.0,
              max(p[0] for p in pts) + 1, 1e9):
        v = band(x, pts)
        assert v is not None and 0.0 <= v <= 10.0 and math.isfinite(v), \
            f"{name} verlaesst bei {x} den Wertebereich"
