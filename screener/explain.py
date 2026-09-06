"""Nachvollziehbarkeit des Gesamtscores: Aufschlüsselung und Signalstärke.

Die Score-Engine rechnet 13 Sub-Scores, von denen bisher NUR die beiden
verdichteten Kennzahlen (`wlatar`, `wlafar`) und der daraus abgeleitete
`total_score` in der Datenbank landeten. Die Einzelwerte wurden nach jedem
Lauf verworfen — die Frage „warum 87?" war aus den gespeicherten Daten
schlicht nicht beantwortbar.

Dieses Modul verdichtet dieselben, ohnehin bereits berechneten Ergebnisse zu
zwei gespeicherten Feldern:

  score_breakdown  — je Faktor: Wert, Gewicht, Beitrag zum Gesamtscore
  signal_strength  — wie viele UNABHÄNGIGE Faktoren sich bestätigen

Zur Signalstärke: Sie beantwortet die Frage, ob ein Treffer auf einer
einzelnen Bedingung beruht oder auf mehreren, die sich gegenseitig stützen.
Ein RSI unter 30 allein ist kein Kaufgrund — erst wenn Trend, Momentum,
relative Stärke und Volumen in dieselbe Richtung zeigen, wird daraus ein
belastbarer Treffer. Genau das macht diese Einstufung sichtbar, statt sie
dem Betrachter zu überlassen.

Kein neuer Rechenaufwand: Alle Werte liegen zum Zeitpunkt des Aufrufs
bereits vor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Die vier Faktoren, deren Übereinstimmung einen Treffer trägt. Bewusst
# UNABHÄNGIGE Dimensionen — Richtung, Schwung, Vergleich zum Markt, Bestätigung
# durch Umsatz. Vier gleichartige Momentum-Indikatoren wären keine Bestätigung,
# sondern dieselbe Aussage in vier Varianten.
CORE_FACTORS: tuple[str, ...] = ("trend", "momentum", "rel_strength", "volume")

CONFIRM_AT = 6.5          # ab diesem Sub-Score (0..10) gilt ein Faktor als bestätigend
CONTRA_AT = 4.0           # darunter spricht er aktiv dagegen


class SignalStrength:
    STRONG = "stark"
    MODERATE = "moderat"
    WEAK = "schwach"
    NONE = "kein Signal"


@dataclass(slots=True)
class Component:
    slug: str
    label: str
    score: float              # 0..100 (anzeigefreundlich)
    weight: float             # Anteil am jeweiligen Composite
    contribution: float       # Beitrag in Punkten des Composites
    state: str | None = None
    available: bool = True


@dataclass(slots=True)
class Breakdown:
    technical: list[Component] = field(default_factory=list)
    fundamental: list[Component] = field(default_factory=list)
    signal_strength: str = SignalStrength.NONE
    confirming: list[str] = field(default_factory=list)
    contradicting: list[str] = field(default_factory=list)
    coverage: float = 0.0             # Anteil des Gewichts mit echten Daten
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        def c(x: Component) -> dict[str, Any]:
            return {"slug": x.slug, "label": x.label, "score": x.score,
                    "weight": x.weight, "contribution": x.contribution,
                    "state": x.state, "available": x.available}
        return {
            "technical": [c(x) for x in self.technical],
            "fundamental": [c(x) for x in self.fundamental],
            "signal_strength": self.signal_strength,
            "confirming": list(self.confirming),
            "contradicting": list(self.contradicting),
            "coverage": round(self.coverage, 3),
            "note": self.note,
        }


def _label_map(computors: list[Any] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for comp in computors or []:
        slug = getattr(comp, "slug", None)
        if slug:
            out[slug] = getattr(comp, "label", None) or slug
    return out


def _components(results: dict[str, Any], weights: dict[str, float],
                labels: dict[str, str]) -> tuple[list[Component], float]:
    """Faktoren eines Composites + Datenabdeckung.

    Fehlende Faktoren werden MITGEFÜHRT (available=False), statt sie zu
    verschweigen: Ein Score, der auf halber Datenlage beruht, muss als solcher
    erkennbar sein — sonst sieht er genauso präzise aus wie ein vollständiger.
    """
    total_w = sum(weights.values()) or 1.0
    present_w = 0.0
    out: list[Component] = []
    for slug, w in sorted(weights.items(), key=lambda kv: -kv[1]):
        res = results.get(slug)
        ok = res is not None and getattr(res, "ok", False)
        raw_score = float(getattr(res, "score", 0.0)) if ok else 0.0
        if ok:
            present_w += w
        out.append(Component(
            slug=slug, label=labels.get(slug, slug),
            score=round(raw_score * 10.0, 1) if ok else 0.0,
            weight=round(w / total_w, 4),
            contribution=round(raw_score * 10.0 * (w / total_w), 1) if ok else 0.0,
            state=getattr(res, "state", None) if ok else None,
            available=ok))
    return out, present_w / total_w


def _classify(results: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    """Signalstärke aus der Übereinstimmung der Kernfaktoren."""
    confirming, contradicting, known = [], [], 0
    for slug in CORE_FACTORS:
        res = results.get(slug)
        if res is None or not getattr(res, "ok", False):
            continue
        known += 1
        s = float(getattr(res, "score", 0.0))
        if s >= CONFIRM_AT:
            confirming.append(slug)
        elif s <= CONTRA_AT:
            contradicting.append(slug)

    # Ohne Datenlage keine Einstufung — lieber „kein Signal" als eine
    # Stärkeangabe, die auf einem einzigen verfügbaren Faktor beruht.
    if known < 2:
        return SignalStrength.NONE, confirming, contradicting
    n = len(confirming)
    if n >= 4 or (n == 3 and known == 3 and not contradicting):
        strength = SignalStrength.STRONG
    elif n >= 2 and len(contradicting) <= 1:
        strength = SignalStrength.MODERATE
    elif n >= 1:
        strength = SignalStrength.WEAK
    else:
        strength = SignalStrength.NONE
    return strength, confirming, contradicting


def build_breakdown(scored: Any, composites: dict[str, dict[str, float]],
                    computors: list[Any] | None = None) -> Breakdown:
    """Aufschlüsselung + Signalstärke aus einem bereits gescorten Instrument."""
    results = getattr(scored, "results", {}) or {}
    labels = _label_map(computors)

    tech, tech_cov = _components(results, composites.get("technical_rating", {}), labels)
    fund, _ = _components(results, composites.get("fundamental_rating", {}), labels)
    strength, confirming, contradicting = _classify(results)

    note = None
    if tech_cov < 0.6:
        note = (f"Nur {tech_cov:.0%} der technischen Gewichtung ist mit Daten "
                f"belegt — der Score ist entsprechend unsicher.")
    return Breakdown(technical=tech, fundamental=fund, signal_strength=strength,
                     confirming=confirming, contradicting=contradicting,
                     coverage=tech_cov, note=note)
