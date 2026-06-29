"""Volume-Score: OBV-Trend, Aufwärts-Volumenanteil, Volumen-Ratio."""
from __future__ import annotations

from ..computor import BaseComputor
from ..context import InstrumentData, ScoringContext
from ..domain import ScoreResult
from ..normalization import band
from ..registry import register_score


@register_score
class VolumeComputor(BaseComputor):
    """Volumen-Qualität: OBV-Richtung, Aufwärts-Anteil, Tagesvolumen-Ratio."""
    slug = "volume"
    label = "Volume"
    family = "momentum_flow"

    def compute(self, data: InstrumentData, ctx: ScoringContext) -> ScoreResult:
        m = data.metric
        vr = m("volume_ratio")      # heutiges Volumen / 20-Tage-Schnitt
        obv_s = m("obv_slope")      # OBV-Änderung normiert auf avg_vol (ca. −1 .. +1)
        up_vol = m("up_vol_ratio")  # Anteil Aufwärts-Volumen letzten 20 Tage (0..1)

        num = den = 0.0
        drivers = []

        if obv_s is not None:
            rs = band(obv_s, [(-1.0, 0), (-0.4, 2), (-0.1, 4), (0.0, 5),
                               (0.1, 7), (0.4, 9), (1.0, 10)])
            num += 0.45 * rs; den += 0.45
            if obv_s > 0.15:
                drivers.append(self.pos("obv_rising",
                    f"OBV steigt — Akkumulationsphase (Slope {obv_s:+.2f})",
                    min(abs(obv_s), 1.0), obv_slope=obv_s))
            elif obv_s < -0.15:
                drivers.append(self.neg("obv_falling",
                    f"OBV fällt — Distributionsphase (Slope {obv_s:+.2f})",
                    min(abs(obv_s), 1.0), obv_slope=obv_s))

        if up_vol is not None:
            rs = band(up_vol, [(0.30, 1), (0.40, 3), (0.48, 5), (0.55, 8), (0.65, 10)])
            num += 0.35 * rs; den += 0.35
            if up_vol >= 0.60:
                drivers.append(self.pos("up_vol_dom",
                    f"Aufwärts-Volumen dominiert ({up_vol:.0%}) — Käufer am Steuer",
                    up_vol - 0.5, up_vol_ratio=up_vol))
            elif up_vol <= 0.40:
                drivers.append(self.neg("down_vol_dom",
                    f"Abwärts-Volumen dominiert ({1 - up_vol:.0%}) — Verkäuferdruck",
                    0.5 - up_vol, up_vol_ratio=up_vol))

        if vr is not None:
            rs = band(vr, [(0.2, 2), (0.5, 4), (0.8, 6), (1.2, 8), (2.0, 9), (4.0, 7)])
            num += 0.20 * rs; den += 0.20

        if den == 0:
            return self.missing("Keine Volumendaten verfügbar")

        score = num / den
        state = "akkumuliert" if score >= 7 else "distribuiert" if score <= 3 else "neutral"
        return self.result(score, state, drivers,
                           volume_ratio=vr, obv_slope=obv_s, up_vol_ratio=up_vol)
