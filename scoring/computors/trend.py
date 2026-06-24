"""Muster A — absolute Banding ohne Universumsbezug."""
from __future__ import annotations

from ..computor import BaseComputor
from ..context import InstrumentData, ScoringContext
from ..domain import ScoreResult
from ..registry import register_score


@register_score
class TrendComputor(BaseComputor):
    """EMA-Konstellation + Kursposition (Punktesystem, Summe 10)."""
    slug = "trend"
    label = "Trend"
    family = "trend_leadership"

    def compute(self, data: InstrumentData, ctx: ScoringContext) -> ScoreResult:
        m = data.metric
        close, e20, e50 = m("close"), m("ema_20"), m("ema_50")
        e100, e200, slope = m("ema_100"), m("ema_200"), m("ema_200_slope")
        if None in (close, e50, e200):
            return self.missing("Kurs oder EMA50/EMA200 fehlt")

        drivers = []
        score = 0.0

        if None not in (e20, e50, e100, e200):
            if e20 > e50 > e100 > e200:
                score += 4.0
                drivers.append(self.pos("ema_stack_bull",
                    "Bullische EMA-Stapelung (20>50>100>200)", 0.9,
                    ema20=e20, ema50=e50, ema100=e100, ema200=e200))
            elif e20 < e50 < e100 < e200:
                drivers.append(self.neg("ema_stack_bear",
                    "Bärische EMA-Stapelung (20<50<100<200)", 0.9))

        if close > e50:
            score += 2.0
            drivers.append(self.pos("above_ema50", "Kurs über EMA50", 0.5))
        else:
            drivers.append(self.neg("below_ema50", "Kurs unter EMA50", 0.5))

        if close > e200:
            score += 2.0
            drivers.append(self.pos("above_ema200", "Kurs über EMA200 (Primärtrend)", 0.6))
        else:
            drivers.append(self.neg("below_ema200", "Kurs unter EMA200 (Primärtrend)", 0.6))

        if slope is not None and slope > 0:
            score += 2.0
            drivers.append(self.pos("ema200_rising", "EMA200 steigt", 0.4))
        elif slope is not None:
            drivers.append(self.neg("ema200_falling", "EMA200 fällt", 0.4))

        state = "Aufwärts" if score >= 7 else "Abwärts" if score <= 3 else "Neutral"
        return self.result(score, state, drivers,
                           close=close, ema50=e50, ema200=e200, slope200=slope)
