"""Breakout-Bereitschaft: Bollinger-Squeeze, Choppiness, ADX/DMI, RSI-Position."""
from __future__ import annotations

from ..computor import BaseComputor
from ..context import InstrumentData, ScoringContext
from ..domain import ScoreResult
from ..normalization import band
from ..registry import register_score


@register_score
class BreakoutComputor(BaseComputor):
    """Misst Kompression→Expansion-Bereitschaft (Wyckoff-Prinzip):
    Squeeze + Trendphase + RSI-Sweet-Spot + DMI-Richtung."""
    slug = "breakout"
    label = "Breakout Setup"
    family = "trend_leadership"

    def compute(self, data: InstrumentData, ctx: ScoringContext) -> ScoreResult:
        m = data.metric
        bb_width = m("bb_width")    # Bollinger-Breite (< 0.05 = Squeeze)
        chop = m("chop")            # Choppiness: < 38 = trendend, > 62 = seitwärts
        rsi_v = m("rsi")            # RSI: 40–65 ideal
        adx_v = m("adx")            # Trendstärke: 15–40 optimal
        dmi_p = m("dmi_plus")
        dmi_m = m("dmi_minus")

        num = den = 0.0
        drivers = []

        # Bollinger-Squeeze: niedrige Breite = Energieaufbau
        if bb_width is not None:
            rs = band(bb_width, [(0.02, 10), (0.04, 9), (0.07, 7),
                                  (0.12, 5), (0.18, 3), (0.25, 1)])
            num += 0.30 * rs; den += 0.30
            if bb_width < 0.05:
                drivers.append(self.pos("bb_squeeze",
                    f"Bollinger-Squeeze (Breite {bb_width:.2%}) — Energie aufgebaut",
                    min((0.10 - bb_width) / 0.10, 1.0), bb_width=bb_width))

        # Choppiness < 38.2 (Fibonacci) = klare Trendphase
        if chop is not None:
            rs = band(chop, [(20, 10), (38, 8), (50, 5), (62, 2), (80, 0)])
            num += 0.25 * rs; den += 0.25
            if chop < 38.2:
                drivers.append(self.pos("trending",
                    f"Choppiness {chop:.1f} — Trendphase, kein Zickzack",
                    min((62 - chop) / 62, 1.0), chop=chop))
            elif chop > 61.8:
                drivers.append(self.neg("choppy",
                    f"Choppiness {chop:.1f} — Seitwärtsphase erschwert Breakout",
                    min((chop - 62) / 30, 1.0), chop=chop))

        # RSI-Sweet-Spot (kein Overbought, genug Momentum)
        if rsi_v is not None:
            rs = band(rsi_v, [(20, 4), (35, 7), (45, 9), (55, 10),
                               (65, 8), (75, 5), (85, 2)])
            num += 0.25 * rs; den += 0.25

        # ADX: Trendbestätigung ohne Überhitzung
        if adx_v is not None:
            rs = band(adx_v, [(5, 2), (15, 5), (20, 8), (30, 10),
                               (42, 8), (55, 5), (70, 2)])
            num += 0.20 * rs; den += 0.20
            if dmi_p is not None and dmi_m is not None:
                if dmi_p > dmi_m:
                    drivers.append(self.pos("dmi_bull",
                        f"DMI+ ({dmi_p:.1f}) > DMI− ({dmi_m:.1f}) — bullisches Momentum",
                        min((dmi_p - dmi_m) / 30, 1.0),
                        dmi_plus=dmi_p, dmi_minus=dmi_m))
                elif dmi_m > dmi_p + 5:
                    drivers.append(self.neg("dmi_bear",
                        f"DMI− ({dmi_m:.1f}) > DMI+ ({dmi_p:.1f}) — bärisches Momentum",
                        min((dmi_m - dmi_p) / 30, 1.0),
                        dmi_plus=dmi_p, dmi_minus=dmi_m))

        if den == 0:
            return self.missing("Keine Breakout-Indikatoren verfügbar")

        score = num / den
        state = "bereit" if score >= 7 else "nicht bereit" if score <= 3 else "neutral"
        return self.result(score, state, drivers,
                           bb_width=bb_width, chop=chop, adx=adx_v, rsi=rsi_v)
