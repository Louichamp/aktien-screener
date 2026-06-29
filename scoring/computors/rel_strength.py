"""Relative Stärke: Rendite-Perzentil ggü. Branchen-/Sektorpeers (cross-sectional)."""
from __future__ import annotations

from ..computor import BaseComputor
from ..context import InstrumentData, ScoringContext
from ..domain import ScoreResult
from ..registry import register_score


@register_score
class RelStrengthComputor(BaseComputor):
    """Relative Stärke der Rendite ggü. der Peer-Gruppe (ret_3m, ret_1m, ret_6m)."""
    slug = "rel_strength"
    label = "Relative Strength"
    family = "trend_leadership"

    FACTORS = (
        ("ret_3m", 0.50),
        ("ret_1m", 0.30),
        ("ret_6m", 0.20),
    )

    def compute(self, data: InstrumentData, ctx: ScoringContext) -> ScoreResult:
        num = den = 0.0
        drivers = []
        scope_used = "sector"

        for key, weight in self.FACTORS:
            ps = ctx.percentile(data, lambda d, k=key: d.metric(k), scope="sector")
            if ps.percentile is None:
                continue
            scope_used = ps.scope
            num += weight * ps.percentile
            den += weight
            pct = round(ps.percentile * 100)
            if ps.percentile >= 0.75:
                drivers.append(self.pos(f"rs_{key}",
                    f"Überdurchschnittliche {key}-Rendite ggü. Branche (Perzentil {pct})",
                    ps.percentile, metric=key, scope=ps.scope, n=ps.n))
            elif ps.percentile <= 0.25:
                drivers.append(self.neg(f"rs_{key}",
                    f"Unterdurchschnittliche {key}-Rendite ggü. Branche (Perzentil {pct})",
                    1.0 - ps.percentile, metric=key, scope=ps.scope, n=ps.n))

        if den == 0:
            return self.missing("Keine Renditedaten für Relativvergleich")

        score = 10.0 * (num / den)
        state = "Relative Stärke" if score >= 7 else "Relative Schwäche" if score <= 3 else "neutral"
        return self.result(score, state, drivers, scope=scope_used)
