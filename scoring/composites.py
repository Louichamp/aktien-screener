"""Headline-Composites als Konfiguration (keine Logik in der Engine).

Technical Rating ≈ WLATAR, Fundamental Rating ≈ WLAFAR, Baseline = Gesamt 0..100.
Ob ein neuer Sub-Score in ein Composite einfließt, ist eine Konfig-Entscheidung
hier — kein Eingriff in die Engine.
"""
from __future__ import annotations

from .domain import ScoreResult

# De-Korrelations-Hinweis: `volume` und `institutional_demand` teilen sich ~2/3
# ihrer Eingaben (up_vol_ratio + obv_slope). Als zwei volle Composite-Posten
# würde der Volumen-Fluss-Faktor doppelt verbucht (Multikollinearität → implizit
# überhöhtes Gewicht). Daher trägt `institutional_demand` ein reduziertes Gewicht
# (sein eigenständiger Informationsgehalt liegt in distribution_days); das frei
# gewordene Gewicht geht an die strukturell ORTHOGONALEN Timing-Signale
# `breakout`/`setup` (Volatilitäts-Kompression ist zur Trailing-Rendite eher
# unkorreliert) — höhere effektive Diversifikation bei gleicher Gewichtssumme.
DEFAULT_COMPOSITES: dict[str, dict[str, float]] = {
    "technical_rating": {
        "trend": .18, "rel_strength": .16, "market_leadership": .12, "momentum": .16,
        "volume": .08, "institutional_demand": .06, "breakout": .12, "setup": .12,
    },
    "fundamental_rating": {
        "fund_quality": .45, "growth": .35, "valuation": .20,
    },
    "total_baseline": {
        "trend": .09, "rel_strength": .08, "market_leadership": .07, "momentum": .10,
        "volume": .04, "institutional_demand": .03, "breakout": .06, "setup": .06,
        "fund_quality": .14, "growth": .12, "valuation": .08, "kronos": .06, "risk": .07,
    },
}


def compose(results: dict[str, ScoreResult], weights: dict[str, float]) -> float | None:
    """Gewichteter Mittelwert über vorhandene, fehlerfreie Sub-Scores (0..10).

    Fehlende/fehlerhafte Slugs werden ausgelassen und die Gewichte über die
    vorhandenen renormiert — dadurch brechen neue oder ausgefallene Scores
    bestehende Composites nicht.
    """
    num = den = 0.0
    for slug, w in weights.items():
        res = results.get(slug)
        if res is None or not res.ok:
            continue
        num += w * res.score
        den += w
    return None if den == 0 else num / den
