"""Zentraler Orchestrator.

Die Engine kennt KEINE score-spezifische Logik. Sie baut den Universums-Kontext,
iteriert über die Registry, fängt Fehler einzelner Computor ab und komponiert
die Headline-Ratings per Konfiguration. Neue Scores erfordern keine Änderung hier.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .composites import DEFAULT_COMPOSITES, compose
from .computor import ScoreComputor
from .context import InstrumentData, ScoringContext
from .domain import Driver, ScoreResult
from .registry import get_computors


@dataclass(slots=True)
class ScoredInstrument:
    """Vollständiges Score-Ergebnis eines Instruments (Mapping auf instrument_scores)."""
    instrument_id: str
    results: dict[str, ScoreResult] = field(default_factory=dict)   # slug -> ScoreResult inkl. drivers
    technical_rating: float | None = None      # 0..10  (≈ WLATAR)
    fundamental_rating: float | None = None    # 0..10  (≈ WLAFAR)
    total_baseline: float | None = None        # 0..100

    def bull_case(self, limit: int = 5) -> list[Driver]:
        """Stärkste positive Treiber über alle Sub-Scores."""
        drivers = [d for r in self.results.values() for d in r.bull_drivers()]
        return sorted(drivers, key=lambda d: d.magnitude, reverse=True)[:limit]

    def bear_case(self, limit: int = 5) -> list[Driver]:
        """Stärkste negative Treiber über alle Sub-Scores."""
        drivers = [d for r in self.results.values() for d in r.bear_drivers()]
        return sorted(drivers, key=lambda d: d.magnitude, reverse=True)[:limit]


class ScoreEngine:
    def __init__(self, computors: list[ScoreComputor] | None = None,
                 composites: dict[str, dict[str, float]] | None = None,
                 min_peers: int = 8) -> None:
        self.computors = computors if computors is not None else get_computors()
        self.composites = composites or DEFAULT_COMPOSITES
        self.min_peers = min_peers

    def score_instrument(self, data: InstrumentData, ctx: ScoringContext) -> ScoredInstrument:
        results: dict[str, ScoreResult] = {}
        for comp in self.computors:
            try:
                results[comp.slug] = comp.compute(data, ctx)
            except Exception as exc:               # Fehlertoleranz: ein Score killt nicht den Lauf
                results[comp.slug] = ScoreResult.error(comp.slug, exc)

        tr = compose(results, self.composites["technical_rating"])
        fr = compose(results, self.composites["fundamental_rating"])
        tb = compose(results, self.composites["total_baseline"])
        return ScoredInstrument(
            instrument_id=data.instrument_id,
            results=results,
            technical_rating=None if tr is None else round(tr, 2),
            fundamental_rating=None if fr is None else round(fr, 2),
            total_baseline=None if tb is None else round(tb * 10, 2),
        )

    def score_universe(self, instruments: list[InstrumentData]) -> dict[str, ScoredInstrument]:
        """Baut den Kontext einmal und bewertet das gesamte Universum."""
        ctx = ScoringContext(instruments, min_peers=self.min_peers)
        return {d.instrument_id: self.score_instrument(d, ctx) for d in instruments}
