"""Momentum: ROC + RSI-Sweetspot (absolute Banding)."""
from __future__ import annotations

from ..computor import BaseComputor
from ..context import InstrumentData, ScoringContext
from ..domain import ScoreResult
from ..normalization import band
from ..registry import register_score


@register_score
class MomentumComputor(BaseComputor):
    slug = "momentum"
    label = "Momentum"
    family = "momentum_flow"

    def compute(self, data: InstrumentData, ctx: ScoringContext) -> ScoreResult:
        m = data.metric
        roc, rsi = m("ret_3m"), m("rsi")
        if roc is None and rsi is None:
            return self.missing("Keine Momentum-Daten")
        num = den = 0.0
        drivers = []
        if roc is not None:
            rs = band(roc, [(-0.2, 1), (0.0, 4), (0.1, 6), (0.3, 9), (0.6, 10)])
            num += 0.6 * rs; den += 0.6
            if rs >= 7:
                drivers.append(self.pos("roc_strong", "3-Monats-Rendite stark", rs / 10, ret_3m=roc))
            elif rs <= 3:
                drivers.append(self.neg("roc_weak", "3-Monats-Rendite schwach", 1 - rs / 10, ret_3m=roc))
        if rsi is not None:
            rss = band(rsi, [(30, 4), (50, 7), (60, 9), (70, 8), (80, 5), (90, 2)])
            num += 0.4 * rss; den += 0.4
        score = num / den if den else 5.0
        state = "stark" if score >= 7 else "schwach" if score <= 3 else "neutral"
        return self.result(score, state, drivers, ret_3m=roc, rsi=rsi)
