"""Der Vertrag, den jeder Sub-Score erfüllt.

`ScoreComputor` ist das Protokoll, das die Engine kennt. `BaseComputor` ist
eine optionale Bequemlichkeits-Basis mit Driver-/Result-Buildern — Plugins
müssen sie nicht erben, solange sie das Protokoll erfüllen.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from .context import InstrumentData, ScoringContext
from .domain import Driver, Polarity, ScoreResult


@runtime_checkable
class ScoreComputor(Protocol):
    slug: str
    label: str
    family: str

    def compute(self, data: InstrumentData, ctx: ScoringContext) -> ScoreResult:
        ...


class BaseComputor(ABC):
    """Optionale Basis: Builder-Helfer reduzieren Boilerplate in den Plugins."""
    slug: str = ""
    label: str = ""
    family: str = ""

    @abstractmethod
    def compute(self, data: InstrumentData, ctx: ScoringContext) -> ScoreResult:
        ...

    # ---- Driver-Builder --------------------------------------------------
    def pos(self, code: str, statement: str, magnitude: float, **evidence: Any) -> Driver:
        return Driver(code, Polarity.POSITIVE, magnitude, statement, evidence)

    def neg(self, code: str, statement: str, magnitude: float, **evidence: Any) -> Driver:
        return Driver(code, Polarity.NEGATIVE, magnitude, statement, evidence)

    def neu(self, code: str, statement: str, **evidence: Any) -> Driver:
        return Driver(code, Polarity.NEUTRAL, 0.0, statement, evidence)

    # ---- Result-Builder --------------------------------------------------
    def result(self, score: float, state: str | None = None,
               drivers: list[Driver] | None = None, **raw: Any) -> ScoreResult:
        return ScoreResult(self.slug, score, state, drivers or [], raw)

    def missing(self, reason: str) -> ScoreResult:
        """Neutrales Ergebnis bei fehlenden Eingangsdaten (kein Fehler)."""
        return ScoreResult(self.slug, 5.0, "Daten unvollständig",
                           [self.neu("missing_data", reason)], {"missing": True})
