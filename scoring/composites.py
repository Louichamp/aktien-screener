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


# Mindest-Datenabdeckung: ein Composite wird nur berichtet, wenn mindestens
# dieser Anteil des GESAMT-Gewichts von tatsächlich vorhandenen Signalen
# gedeckt ist. Ohne dieses Gate kann EIN einziges Signal (z. B. market_leadership,
# das rein aus Fundamentaldaten-Peer-Perzentilen kommt und keine Kerzen braucht)
# bei fast komplett fehlenden übrigen Signalen ein volles, selbstbewusst
# wirkendes Rating erzeugen — live beobachtet: ein Titel mit nur 1 Kerze
# Historie (dünn gehandeltes/neu gelistetes Wertpapier) bekam WLATAR 9/10 und
# "STARK KAUFEN" 87/100, obwohl 7 von 8 technischen Signalen fehlten. Der
# Schwellwert 0.3 ist bewusst konservativ (nicht 0.5): ein Composite mit z. B.
# drei von acht etwa gleich gewichteten Signalen soll noch ein Rating zeigen
# dürfen, nur die Extremfälle (fast alles fehlt) werden abgefangen.
MIN_COVERAGE = 0.3


def compose(results: dict[str, ScoreResult], weights: dict[str, float],
           *, min_coverage: float = MIN_COVERAGE) -> float | None:
    """Gewichteter Mittelwert über vorhandene, fehlerfreie Sub-Scores (0..10).

    Fehlende/fehlerhafte Slugs werden ausgelassen und die Gewichte über die
    vorhandenen renormiert — dadurch brechen neue oder ausgefallene Scores
    bestehende Composites nicht. Deckt die Summe der vorhandenen Gewichte
    weniger als `min_coverage` des theoretischen Gesamtgewichts ab, gilt das
    Composite als nicht belastbar und liefert `None` (ehrliches "unbekannt")
    statt eines möglicherweise irreführenden Werts aus 1-2 Signalen.
    """
    num = den = 0.0
    for slug, w in weights.items():
        res = results.get(slug)
        if res is None or not res.ok:
            continue
        num += w * res.score
        den += w
    total_weight = sum(weights.values())
    if den == 0 or (total_weight > 0 and den / total_weight < min_coverage):
        return None
    return num / den
