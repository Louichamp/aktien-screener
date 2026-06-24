"""Fundamental Quality: ROIC, Nettomarge, Verschuldung (Banding)."""
from __future__ import annotations

from ..computor import BaseComputor
from ..context import InstrumentData, ScoringContext
from ..domain import ScoreResult
from ..normalization import band
from ..registry import register_score


@register_score
class FundQualityComputor(BaseComputor):
    slug = "fund_quality"
    label = "Fundamental Quality"
    family = "quality"

    def compute(self, data: InstrumentData, ctx: ScoringContext) -> ScoreResult:
        m = data.metric
        roic, margin, de = m("roic"), m("net_margin"), m("debt_equity")
        num = den = 0.0
        drivers = []
        if roic is not None:
            rs = band(roic, [(0.0, 2), (0.08, 5), (0.15, 7), (0.25, 9), (0.4, 10)])
            num += 0.45 * rs; den += 0.45
            if rs >= 7:
                drivers.append(self.pos("roic_high", f"Hohe Kapitalrendite (ROIC {roic:.0%})", rs / 10, roic=roic))
        if margin is not None:
            rs = band(margin, [(0.0, 2), (0.1, 5), (0.2, 8), (0.35, 10)])
            num += 0.35 * rs; den += 0.35
        if de is not None:
            rs = band(de, [(0.0, 10), (1.0, 7), (2.0, 4), (3.0, 2)])
            num += 0.20 * rs; den += 0.20
            if de >= 2.0:
                drivers.append(self.neg("high_debt", f"Hohe Verschuldung (D/E {de:.1f})", min((de - 1) / 2, 1), debt_equity=de))
        if den == 0:
            return self.missing("Keine Qualitäts-Kennzahlen")
        score = num / den
        state = "hochwertig" if score >= 7 else "schwach" if score <= 3 else "solide"
        return self.result(score, state, drivers, roic=roic, net_margin=margin, debt_equity=de)
