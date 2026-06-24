"""Risk: 10 = geringstes Risiko (Volatilität + Verschuldung)."""
from __future__ import annotations

from ..computor import BaseComputor
from ..context import InstrumentData, ScoringContext
from ..domain import ScoreResult
from ..normalization import band
from ..registry import register_score


@register_score
class RiskComputor(BaseComputor):
    slug = "risk"
    label = "Risk"
    family = "risk"

    def compute(self, data: InstrumentData, ctx: ScoringContext) -> ScoreResult:
        m = data.metric
        close, atr, de = m("close"), m("atr"), m("debt_equity")
        num = den = 0.0
        drivers = []
        if close and atr:
            atr_pct = atr / close
            rs = band(atr_pct, [(0.01, 10), (0.02, 8), (0.03, 6), (0.05, 4), (0.08, 2)])
            num += 0.6 * rs; den += 0.6
            if atr_pct >= 0.05:
                drivers.append(self.neg("high_vola", f"Hohe Volatilität (ATR {atr_pct:.1%})", min(atr_pct / 0.1, 1), atr_pct=atr_pct))
        if de is not None:
            rs = band(de, [(0.0, 10), (1.0, 8), (2.0, 5), (3.0, 2)])
            num += 0.4 * rs; den += 0.4
        if den == 0:
            return self.missing("Keine Risikodaten")
        score = num / den               # 10 = sicher
        state = "defensiv" if score >= 7 else "riskant" if score <= 3 else "mittel"
        return self.result(score, state, drivers, atr=atr, debt_equity=de)
