"""Muster B — sektor-neutrale, cross-sectional Normalisierung (invertiert).

NICHT-POSITIVE MULTIPLIKATOREN: Ein negatives KGV/EV-EBITDA/KBV bedeutet nicht
„billig", sondern dass die Kennzahl als Bewertungsmassstab NICHT DEFINIERT ist
(negatives Ergebnis, negatives EBITDA, negatives Eigenkapital). Die Invertierung
„klein ist besser" dreht solche Werte aber an die Spitze der Rangliste.

Gemessen im Produktions-Querschnitt vom 2026-09-06 (4906 Titel), bevor dieser
Filter existierte:

    EV/EBITDA negativ   92 von 633 (14,5 %)  ->  mittleres invertiertes
                                                 Perzentil 0,70 (positiv: 0,46)
    P/B       negativ   66 von 712 ( 9,3 %)  ->  mittleres Perzentil 0,77

    AHG  EV/EBITDA -447,5  ->  Perzentil 0,95 („billigst der Branche")
    MCK  P/B        -24,8  ->  Perzentil 0,92 (negatives Eigenkapital)

Verlustfirmen und Gesellschaften mit negativem Buchwert bekamen so systematisch
einen Bewertungsbonus. Nicht-positive Multiplikatoren werden deshalb wie
FEHLEND behandelt — sowohl beim eigenen Wert als auch in der Peer-Verteilung,
damit sie auch die Ränge der gültigen Titel nicht verschieben.

Bewusst NICHT als „teuer" (Perzentil 0) gewertet: Das wäre eine zusätzliche
Behauptung. Die fehlende Profitabilität ist über `fund_quality` (net_margin,
roic) und `growth` (eps_growth) bereits erfasst; hier gilt konsequent
„ehrliches Unbekannt" statt eines erfundenen Werts.

Winsorizing (wie bei den Renditemomenten) ist hier NICHT nötig: Die Bewertung
läuft über RÄNGE, nicht über Niveaus — ein Ausreisser von +4000 KGV belegt
denselben letzten Rang wie einer von +400.
"""
from __future__ import annotations

from statistics import mean

from ..computor import BaseComputor
from ..context import InstrumentData, ScoringContext
from ..domain import ScoreResult
from ..registry import register_score


def _positive_multiple(data: InstrumentData, key: str) -> float | None:
    """Multiplikator nur, wenn er als Bewertungsmassstab definiert ist (> 0)."""
    v = data.metric(key)
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0.0 else None


@register_score
class ValuationComputor(BaseComputor):
    """Günstigkeit ggü. Branchen-Peers (kleiner Multiplikator = höher)."""
    slug = "valuation"
    label = "Valuation"
    family = "value"
    MULTIPLES = ("pe", "ev_ebitda", "p_fcf", "p_b")

    def compute(self, data: InstrumentData, ctx: ScoringContext) -> ScoreResult:
        parts: list[float] = []
        drivers = []
        used_scope = "industry"
        undefined: list[str] = []

        for key in self.MULTIPLES:
            raw = data.metric(key)
            if raw is not None and _positive_multiple(data, key) is None:
                undefined.append(key.upper())        # vorhanden, aber <= 0
            ps = ctx.percentile(data, lambda d, k=key: _positive_multiple(d, k),
                                scope="industry", invert=True)
            if ps.percentile is None:
                continue
            used_scope = ps.scope
            parts.append(ps.percentile)
            pct = round(ps.percentile * 100)
            if ps.percentile >= 0.7:
                drivers.append(self.pos(f"cheap_{key}",
                    f"{key.upper()} günstig ggü. Peers (Perzentil {pct})",
                    ps.percentile, metric=key, scope=ps.scope, n=ps.n))
            elif ps.percentile <= 0.3:
                drivers.append(self.neg(f"rich_{key}",
                    f"{key.upper()} teuer ggü. Peers (Perzentil {pct})",
                    1.0 - ps.percentile, metric=key, scope=ps.scope, n=ps.n))

        if undefined:
            drivers.append(self.neu("multiple_undefined",
                f"{', '.join(undefined)} nicht positiv (Verlust bzw. negatives "
                f"Eigenkapital) — als Bewertungsmassstab nicht verwendbar",
                metrics=undefined))

        if not parts:
            return self.missing("Keine positiven Bewertungsmultiplikatoren verfügbar")

        if used_scope != "industry":
            drivers.append(self.neu("peer_fallback",
                f"Vergleich gegen {used_scope} (zu wenige Branchen-Peers)",
                scope=used_scope))

        score = 10.0 * mean(parts)
        state = "Günstig" if score >= 7 else "Teuer" if score <= 3 else "Fair"
        return self.result(score, state, drivers,
                           multiples_used=len(parts), scope=used_scope)
