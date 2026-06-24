"""Growth: Umsatz- und EPS-Wachstum (Banding)."""
from __future__ import annotations

from ..computor import BaseComputor
from ..context import InstrumentData, ScoringContext
from ..domain import ScoreResult
from ..normalization import band
from ..registry import register_score


@register_score
class GrowthComputor(BaseComputor):
    slug = "growth"
    label = "Growth"
    family = "growth"

    def compute(self, data: InstrumentData, ctx: ScoringContext) -> ScoreResult:
        m = data.metric
        rev, eps = m("revenue_growth"), m("eps_growth")
        if rev is None and eps is None:
            return self.missing("Keine Wachstumsdaten")
        scale = [(0.0, 2), (0.05, 4), (0.15, 6), (0.25, 8), (0.5, 10)]
        num = den = 0.0
        drivers = []
        if rev is not None:
            rs = band(rev, scale); num += 0.6 * rs; den += 0.6
            if rs >= 7:
                drivers.append(self.pos("rev_growth", f"Hohes Umsatzwachstum ({rev:.0%})", rs / 10, revenue_growth=rev))
        if eps is not None:
            rs = band(eps, scale); num += 0.4 * rs; den += 0.4
        score = num / den
        state = "wachstumsstark" if score >= 7 else "stagnierend" if score <= 3 else "moderat"
        return self.result(score, state, drivers, revenue_growth=rev, eps_growth=eps)
