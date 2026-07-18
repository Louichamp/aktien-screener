"""Tests für compose() — insbesondere das Mindest-Datenabdeckungs-Gate.

Live-Vorfall (2026-07-18): ein Wertpapier mit nur 1 Kerze Kurshistorie
(dünn gehandelter Warrant, von Yahoo nicht von normalen Aktien unterscheidbar)
bekam WLATAR 9/10 und "STARK KAUFEN" 87/100 — obwohl 7 von 8 technischen
Signalen als "missing" markiert waren und nur `market_leadership` (das rein
aus Fundamentaldaten-Peer-Perzentilen kommt, keine Kerzen braucht) einen Wert
lieferte. compose() muss ein Composite aus nahezu keinen echten Signalen als
nicht belastbar erkennen und `None` statt eines irreführenden Werts liefern.
"""
from __future__ import annotations

from scoring.composites import DEFAULT_COMPOSITES, compose
from scoring.domain import ScoreResult


def test_compose_suppresses_rating_from_single_signal():
    """Nur 1 von 8 Signalen (Gewicht 0.12 von 1.00) -> unter der 0.3-Schwelle -> None."""
    weights = DEFAULT_COMPOSITES["technical_rating"]
    results = {slug: ScoreResult(slug, 5.0, ok=False) for slug in weights}
    results["market_leadership"] = ScoreResult("market_leadership", 9.0, ok=True)

    assert compose(results, weights) is None


def test_compose_keeps_rating_with_sufficient_coverage():
    """4 von 8 Signalen, deutlich über der 0.3-Schwelle -> normales Rating."""
    weights = DEFAULT_COMPOSITES["technical_rating"]
    results = {slug: ScoreResult(slug, 5.0, ok=False) for slug in weights}
    results["market_leadership"] = ScoreResult("market_leadership", 9.0, ok=True)
    results["trend"] = ScoreResult("trend", 8.0, ok=True)
    results["momentum"] = ScoreResult("momentum", 7.0, ok=True)
    results["setup"] = ScoreResult("setup", 7.5, ok=True)

    score = compose(results, weights)
    assert score is not None
    assert 0.0 <= score <= 10.0


def test_compose_custom_min_coverage_threshold():
    """min_coverage ist parametrisierbar (nicht nur der globale Default)."""
    weights = {"a": 0.5, "b": 0.5}
    results = {"a": ScoreResult("a", 8.0, ok=True), "b": ScoreResult("b", 5.0, ok=False)}

    assert compose(results, weights, min_coverage=0.3) is not None   # 0.5 Coverage >= 0.3
    assert compose(results, weights, min_coverage=0.6) is None       # 0.5 Coverage < 0.6


def test_compose_all_missing_returns_none():
    weights = DEFAULT_COMPOSITES["fundamental_rating"]
    results = {slug: ScoreResult(slug, 5.0, ok=False) for slug in weights}
    assert compose(results, weights) is None


def test_compose_full_coverage_matches_plain_weighted_average():
    """Bei 100% Coverage verhält sich compose() wie ein normaler gewichteter Schnitt."""
    weights = {"a": 0.6, "b": 0.4}
    results = {"a": ScoreResult("a", 8.0, ok=True), "b": ScoreResult("b", 4.0, ok=True)}
    score = compose(results, weights)
    assert score == 0.6 * 8.0 + 0.4 * 4.0
