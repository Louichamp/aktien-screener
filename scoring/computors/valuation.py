"""Muster B — sektor-neutrale, cross-sectional Normalisierung (invertiert)."""
from __future__ import annotations

from statistics import mean

from ..computor import BaseComputor
from ..context import InstrumentData, ScoringContext
from ..domain import ScoreResult
from ..registry import register_score


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

        for key in self.MULTIPLES:
            ps = ctx.percentile(data, lambda d, k=key: d.metric(k),
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

        if not parts:
            return self.missing("Keine Bewertungsmultiplikatoren verfügbar")

        if used_scope != "industry":
            drivers.append(self.neu("peer_fallback",
                f"Vergleich gegen {used_scope} (zu wenige Branchen-Peers)",
                scope=used_scope))

        score = 10.0 * mean(parts)
        state = "Günstig" if score >= 7 else "Teuer" if score <= 3 else "Fair"
        return self.result(score, state, drivers,
                           multiples_used=len(parts), scope=used_scope)
