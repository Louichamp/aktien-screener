"""Tests der empirischen Validierungs-Schicht (IC, Regime, Orthogonalität, Decision)."""
from __future__ import annotations

import math

import pytest

from scoring.context import InstrumentData
from scoring.domain import ScoreResult
from scoring.validation import (classify_regime, decision_quality, ic_summary,
                                rank_ic, redundancy_report, regularized_weights,
                                signal_half_life)
from scoring.validation.ic import ICStats


# ── Rang-IC ───────────────────────────────────────────────────────────────────

def test_rank_ic_perfect_monotonic():
    sig = [1, 2, 3, 4, 5]
    fwd = [0.1, 0.2, 0.3, 0.4, 0.5]
    assert rank_ic(sig, fwd) == pytest.approx(1.0)


def test_rank_ic_perfect_inverse():
    sig = [1, 2, 3, 4, 5]
    fwd = [0.5, 0.4, 0.3, 0.2, 0.1]
    assert rank_ic(sig, fwd) == pytest.approx(-1.0)


def test_rank_ic_is_rank_based_not_linear():
    # Monotone, aber stark nichtlineare Beziehung → Spearman bleibt 1.0.
    sig = [1, 2, 3, 4, 5]
    fwd = [1, 4, 9, 16, 25]
    assert rank_ic(sig, fwd) == pytest.approx(1.0)


def test_rank_ic_degenerate_returns_none():
    assert rank_ic([1, 1, 1, 1], [1, 2, 3, 4]) is None      # konstantes Signal
    assert rank_ic([1, 2], [1, 2]) is None                  # zu wenige Punkte


# ── IC-Aggregation ────────────────────────────────────────────────────────────

def test_ic_summary_stats():
    series = [0.05, 0.04, 0.06, 0.05, 0.05, 0.04, 0.06, 0.05, 0.05, 0.04, 0.06, 0.05]
    st = ic_summary("trend", series)
    assert st is not None
    assert st.ic_mean == pytest.approx(sum(series) / len(series))
    assert st.hit_rate == 1.0                       # alle positiv
    assert st.ic_t_stat > 2.0                       # stabile, signifikante Kante
    assert st.reliable


def test_ic_summary_unstable_signal_not_reliable():
    series = [0.3, -0.3, 0.25, -0.28, 0.3, -0.31, 0.2, -0.22, 0.3, -0.3, 0.27, -0.29]
    st = ic_summary("noise", series)
    assert st is not None
    assert abs(st.ic_mean) < 0.05                   # mittelt sich weg
    assert not st.reliable                          # kein Vorzeichen-Konsens


def test_ic_summary_by_regime():
    series = [0.10, 0.12, 0.08, -0.02, -0.01, 0.00]
    regimes = ["trend", "trend", "trend", "chop", "chop", "chop"]
    st = ic_summary("momentum", series, regimes)
    assert st.by_regime["trend"] == pytest.approx(0.10, abs=1e-9)
    assert st.by_regime["chop"] == pytest.approx(-0.01, abs=1e-9)


# ── Signal-Halbwertszeit ──────────────────────────────────────────────────────

def test_signal_half_life_interpolates():
    # Peak |IC| = 0.10 bei h=5; halbiert (0.05) zwischen h=20 (0.06) und h=40 (0.04).
    ic_by_h = {5: 0.10, 10: 0.08, 20: 0.06, 40: 0.04}
    hl = signal_half_life(ic_by_h)
    assert 20 < hl < 40


# ── Regularisierte Gewichte (Error-Correction-Kern) ──────────────────────────

def _stats(slug, ic_mean, t_stat, n=24):
    return ICStats(slug, ic_mean, 0.05, t_stat, 0.7, n, {})


def test_weights_no_evidence_is_noop():
    prior = {"a": 0.5, "b": 0.3, "c": 0.2}
    out = regularized_weights(prior, {})            # keine IC-Statistik
    assert out == pytest.approx(prior)


def test_weights_reward_stable_positive_ic():
    prior = {"good": 0.5, "bad": 0.5}
    stats = {
        "good": _stats("good", 0.08, 4.0),          # starke, signifikante Kante
        "bad": _stats("bad", 0.0, 0.0),             # keine Kante
    }
    out = regularized_weights(prior, stats)
    assert out["good"] > prior["good"]              # hochgewichtet
    assert out["bad"] < prior["bad"]               # relativ runter (Renormierung)
    assert sum(out.values()) == pytest.approx(sum(prior.values()))   # Skala erhalten


def test_weights_penalize_negative_ic():
    prior = {"harmful": 0.5, "neutral": 0.5}
    stats = {
        "harmful": _stats("harmful", -0.08, 4.0),   # anti-prädiktiv, signifikant
        "neutral": _stats("neutral", 0.0, 0.0),
    }
    out = regularized_weights(prior, stats)
    assert out["harmful"] < prior["harmful"]        # Vertrauensentzug
    assert out["harmful"] > 0                       # aber nicht negativ/eliminiert


def test_weights_respect_max_tilt_cap():
    prior = {"x": 0.5, "y": 0.5}
    stats = {"x": _stats("x", 5.0, 50.0), "y": _stats("y", 0.0, 0.0)}   # absurd starke Evidenz
    out = regularized_weights(prior, stats, max_tilt=0.5)
    # raw_x ≤ prior·1.5 ⇒ nach Renormierung bleibt der Tilt gedeckelt.
    assert out["x"] <= prior["x"] * 1.5 + 1e-9


# ── Regime ────────────────────────────────────────────────────────────────────

def test_regime_low_vol_coherent_trend():
    panel = [{"realized_vol": 0.15, "efficiency_ratio": 0.6, "above_ema200": 1, "ret_1m": 3.0}
             for _ in range(20)]
    rg = classify_regime(panel)
    assert rg.vol == "low"
    assert rg.trend == "coherent"


def test_regime_stress_incoherent():
    panel = [{"realized_vol": 0.60, "efficiency_ratio": 0.1, "above_ema200": 0, "ret_1m": -5.0}
             for _ in range(20)]
    rg = classify_regime(panel)
    assert rg.vol == "stress"
    assert rg.trend == "incoherent"


# ── Orthogonalität / Redundanz ────────────────────────────────────────────────

def test_redundancy_detects_duplicate_signals():
    # 'a' und 'b' sind identisch (perfekt korreliert); 'c' ist unabhängig.
    import random
    random.seed(1)
    panel = []
    for _ in range(40):
        a = random.uniform(0, 10)
        panel.append({"a": a, "b": a, "c": random.uniform(0, 10)})
    rep = redundancy_report(panel, ["a", "b", "c"], threshold=0.7)
    assert ["a", "b"] in rep["clusters"]
    assert rep["effective_signals"] < 3.0           # weniger als 3 unabhängige Signale
    assert rep["redundancy"]["a"] > rep["redundancy"]["c"]


# ── Decision Quality (Output-Layer) ──────────────────────────────────────────

def _inst(**tech):
    return InstrumentData(instrument_id="X", ticker="X", asset_class="Aktie",
                          technicals=tech)


def test_decision_quality_high_confidence_when_aligned():
    results = {
        "trend": ScoreResult("trend", 8.0),
        "momentum": ScoreResult("momentum", 8.2),
        "rel_strength": ScoreResult("rel_strength", 7.8),
    }
    weights = {"trend": 0.4, "momentum": 0.3, "rel_strength": 0.3}
    data = _inst(realized_vol=0.18, max_drawdown=0.10, efficiency_ratio=0.7)
    dq = decision_quality(results, data, weights)
    assert dq.coverage == pytest.approx(1.0)
    assert dq.agreement > 0.9                       # eng beieinander
    assert dq.confidence > 0.5


def test_decision_quality_drops_on_conflict_and_missing():
    results = {
        "trend": ScoreResult("trend", 9.0),
        "momentum": ScoreResult("momentum", 2.0),   # widersprüchlich
        # rel_strength fehlt (ok=False)
        "rel_strength": ScoreResult("rel_strength", 5.0, ok=False),
    }
    weights = {"trend": 0.4, "momentum": 0.3, "rel_strength": 0.3}
    data = _inst(realized_vol=0.55, max_drawdown=0.40, efficiency_ratio=0.15)
    dq = decision_quality(results, data, weights)
    assert dq.coverage == pytest.approx(0.7)        # rel_strength fehlt
    assert dq.agreement < 0.5                        # Trend vs. Momentum uneins
    assert dq.instability > 0.5                      # hohe Vola/Drawdown/Zickzack
    assert dq.confidence < 0.2
