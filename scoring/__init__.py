"""Score-Engine: Plugin-basiertes, sektor-neutrales Bewertungsmodell.

Der Import dieses Pakets entdeckt automatisch alle Computor-Plugins im
`computors`-Unterpaket (`@register_score`), sodass `ScoreEngine()` ohne
weitere Verdrahtung die volle Registry nutzt.
"""
from __future__ import annotations

from .composites import DEFAULT_COMPOSITES, compose
from .context import InstrumentData, PeerStat, ScoringContext
from .domain import Driver, Polarity, ScoreResult
from .engine import ScoredInstrument, ScoreEngine
from .registry import discover_computors, get_computors, register_score

# Auto-Discovery der Score-Plugins (idempotent dank Registry-Guard).
discover_computors(f"{__name__}.computors")

__all__ = [
    "InstrumentData", "PeerStat", "ScoringContext",
    "Driver", "Polarity", "ScoreResult",
    "ScoredInstrument", "ScoreEngine",
    "DEFAULT_COMPOSITES", "compose",
    "discover_computors", "get_computors", "register_score",
]
