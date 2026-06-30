"""Entscheidungs-Qualität — das finale Output-Layer.

Ein Ranking allein ist keine Entscheidung. Eine Empfehlung muss sagen, WIE
belastbar ihre eigene Einordnung ist. Aus den bereits berechneten Sub-Scores
und Roh-Technicals eines Titels werden vier interpretierbare Maße verdichtet:

  • coverage       — Daten-Vollständigkeit: gewichteter Anteil tatsächlich
                     vorhandener Signale (fehlende werden NICHT als neutral
                     imputiert — konsistent zur compose()/missing()-Logik).
  • agreement      — Signal-Konsens: 1 − normierte Streuung der (gleich
                     orientierten) Sub-Scores. Hoch = die Signale ziehen am
                     selben Strang; niedrig = widersprüchliche Evidenz.
  • instability    — Struktur-Instabilität des Titels selbst (realisierte Vola,
                     Max-Drawdown, geringe Trend-Effizienz). Hoch = die
                     Preisstruktur ist verrauscht ⇒ jedes Ranking ist fragiler.
  • confidence     — coverage · agreement · (1 − instability): die zusammengefasste
                     Verlässlichkeit der Einordnung unter wechselnden Bedingungen.

Alles deterministisch, O(#Signale), keine externen Abhängigkeiten.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..context import InstrumentData
from ..domain import ScoreResult

# Maximale Streuung zweier 0..10-Scores um den Mittelwert (für Normierung).
_MAX_DISPERSION = 5.0


@dataclass(slots=True)
class DecisionQuality:
    confidence: float          # 0..1 Gesamt-Verlässlichkeit des Rankings
    coverage: float            # 0..1 Daten-Vollständigkeit (gewichtet)
    agreement: float           # 0..1 Signal-Konsens
    instability: float         # 0..1 Struktur-Instabilität (höher = riskanter)
    n_signals: int             # Anzahl vorhandener, fehlerfreier Signale

    def as_dict(self) -> dict[str, float | int]:
        return {
            "confidence": round(self.confidence, 3),
            "coverage": round(self.coverage, 3),
            "agreement": round(self.agreement, 3),
            "instability": round(self.instability, 3),
            "n_signals": self.n_signals,
        }


def _instability(data: InstrumentData) -> float:
    """Struktur-Instabilität 0..1 aus realisierter Vola, Drawdown, Trend-Effizienz.

    Jede Komponente wird auf 0..1 normiert und gemittelt; fehlende Komponenten
    werden ausgelassen. Geringe Efficiency Ratio erhöht die Instabilität (Zickzack).
    """
    parts: list[float] = []
    rv = data.metric("realized_vol")
    if rv is not None:
        parts.append(min(max(rv / 0.80, 0.0), 1.0))         # 80 % p.a. ≈ Maximalskala
    mdd = data.metric("max_drawdown")
    if mdd is not None:
        parts.append(min(max(mdd / 0.60, 0.0), 1.0))        # 60 % Drawdown ≈ Maximalskala
    er = data.metric("efficiency_ratio")
    if er is not None:
        parts.append(min(max(1.0 - er, 0.0), 1.0))          # niedrige ER = instabil
    if not parts:
        return 0.5                                          # unbekannt → neutral
    return sum(parts) / len(parts)


def decision_quality(results: dict[str, ScoreResult], data: InstrumentData,
                     weights: dict[str, float]) -> DecisionQuality:
    """Verdichtet Sub-Scores + Roh-Technicals zu Entscheidungs-Qualitätsmaßen.

    `weights` ist typischerweise das technical_rating-Composite (oder eine Union
    der relevanten Gewichte); es bestimmt Coverage- und Agreement-Gewichtung.
    """
    present: list[tuple[float, float]] = []     # (gewicht, score) der vorhandenen Signale
    total_w = 0.0
    for slug, w in weights.items():
        total_w += w
        res = results.get(slug)
        if res is not None and res.ok and not res.raw.get("missing"):
            present.append((w, res.score))

    coverage = (sum(w for w, _ in present) / total_w) if total_w > 0 else 0.0

    if len(present) >= 2:
        wsum = sum(w for w, _ in present)
        mean = sum(w * s for w, s in present) / wsum
        var = sum(w * (s - mean) ** 2 for w, s in present) / wsum
        dispersion = min(var ** 0.5 / _MAX_DISPERSION, 1.0)
        agreement = 1.0 - dispersion
    else:
        agreement = 0.0                          # zu wenige Signale für Konsens

    instab = _instability(data)
    confidence = max(0.0, min(1.0, coverage * agreement * (1.0 - instab)))
    return DecisionQuality(confidence, coverage, agreement, instab, len(present))
