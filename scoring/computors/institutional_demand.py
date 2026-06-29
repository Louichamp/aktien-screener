"""Institutionelle Nachfrage: Distributionstage, Aufwärts-Volumen, OBV."""
from __future__ import annotations

from ..computor import BaseComputor
from ..context import InstrumentData, ScoringContext
from ..domain import ScoreResult
from ..normalization import band
from ..registry import register_score


@register_score
class InstitutionalDemandComputor(BaseComputor):
    """Proxy für institutionelle Akkumulation vs. Distribution."""
    slug = "institutional_demand"
    label = "Institutional Demand"
    family = "momentum_flow"

    def compute(self, data: InstrumentData, ctx: ScoringContext) -> ScoreResult:
        m = data.metric
        dist = m("distribution_days")   # 0..10 (weniger ist besser)
        up_vol = m("up_vol_ratio")      # 0..1
        obv_s = m("obv_slope")          # normierter OBV-Trend

        num = den = 0.0
        drivers = []

        if dist is not None:
            rs = band(dist, [(0, 10), (2, 8), (3, 6), (5, 3), (7, 1)])
            num += 0.40 * rs; den += 0.40
            if dist >= 5:
                drivers.append(self.neg("dist_pressure",
                    f"{int(dist)} Distributionstage — institutioneller Verkaufsdruck",
                    min(dist / 8.0, 1.0), distribution_days=dist))
            elif dist <= 1:
                drivers.append(self.pos("low_dist",
                    "Kaum Distribution — Institutionelle halten Positionen",
                    0.40, distribution_days=dist))

        if up_vol is not None:
            rs = band(up_vol, [(0.30, 1), (0.42, 3), (0.50, 6), (0.58, 9), (0.70, 10)])
            num += 0.35 * rs; den += 0.35
            if up_vol >= 0.58:
                drivers.append(self.pos("inst_buying",
                    f"Institutionelle Akkumulation: Aufwärts-Volumen {up_vol:.0%}",
                    up_vol - 0.5, up_vol_ratio=up_vol))
            elif up_vol <= 0.42:
                drivers.append(self.neg("inst_selling",
                    f"Institutioneller Abgabedruck: Abwärts-Volumen {1 - up_vol:.0%}",
                    0.5 - up_vol, up_vol_ratio=up_vol))

        if obv_s is not None:
            rs = band(obv_s, [(-1.0, 0), (-0.3, 2), (0.0, 5), (0.3, 8), (0.7, 10)])
            num += 0.25 * rs; den += 0.25

        if den == 0:
            return self.missing("Keine institutionellen Signale verfügbar")

        score = num / den
        state = "Akkumulation" if score >= 7 else "Distribution" if score <= 3 else "neutral"
        return self.result(score, state, drivers,
                           distribution_days=dist, up_vol_ratio=up_vol, obv_slope=obv_s)
