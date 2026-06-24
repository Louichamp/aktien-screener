"""Kern-Datentypen der Score-Engine.

Bewusst abhängigkeitsfrei (nur stdlib), damit sie überall importierbar sind
und keine zyklischen Importe entstehen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Polarity(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


@dataclass(slots=True)
class Driver:
    """Ein einzelner Begründungs-Treiber eines Scores.

    `statement` ist ein fertiger, anzeigbarer deutscher Satz; `magnitude`
    (0..1) ist die Wirkungsstärke und steuert die Sortierung im Bull/Bear-Case.
    """
    code: str
    polarity: Polarity
    magnitude: float
    statement: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.magnitude = max(0.0, min(1.0, float(self.magnitude)))


@dataclass(slots=True)
class ScoreResult:
    """Ergebnis eines Sub-Scores: Zahl + Zustand + strukturierte Begründung."""
    slug: str
    score: float                       # 0..10
    state: str | None = None
    drivers: list[Driver] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    ok: bool = True                    # False = Berechnungsfehler (von Komposition ausgeschlossen)

    def __post_init__(self) -> None:
        self.score = max(0.0, min(10.0, float(self.score)))

    def bull_drivers(self) -> list[Driver]:
        return sorted(
            (d for d in self.drivers if d.polarity is Polarity.POSITIVE),
            key=lambda d: d.magnitude, reverse=True,
        )

    def bear_drivers(self) -> list[Driver]:
        return sorted(
            (d for d in self.drivers if d.polarity is Polarity.NEGATIVE),
            key=lambda d: d.magnitude, reverse=True,
        )

    @classmethod
    def error(cls, slug: str, exc: Exception) -> "ScoreResult":
        """Neutrales Fehler-Ergebnis, falls ein Computor eine Exception wirft."""
        return cls(
            slug=slug, score=5.0, state="Berechnungsfehler", ok=False,
            drivers=[Driver("compute_error", Polarity.NEUTRAL, 0.0,
                            f"Score nicht berechenbar: {exc}", {"error": repr(exc)})],
        )
