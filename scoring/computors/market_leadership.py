"""Muster C — Peer-Gruppen-Score über mehrere Faktoren.

Market Leadership grenzt sich bewusst von Relative Strength ab: RS misst gegen
den breiten Benchmark, Leadership gegen die *direkten Branchen-Peers* — Performance-
UND fundamentale Führerschaft (Margen, ROIC, Größe). Das Peer-Grouping inkl.
Fallback liefert der Kontext; der Computor deklariert nur seine Faktoren.
"""
from __future__ import annotations

from ..computor import BaseComputor
from ..context import InstrumentData, PeerStat, ScoringContext
from ..domain import ScoreResult
from ..registry import register_score


@register_score
class MarketLeadershipComputor(BaseComputor):
    slug = "market_leadership"
    label = "Market Leadership"
    family = "trend_leadership"

    # (Metrik, Gewicht, kleiner_ist_besser)
    # De-Korrelation: ret_3m treibt bereits rel_strength (.50) und momentum.
    # Mit 0.40 wäre Leadership ein dritter Momentum-Proxy (Dreifachverbuchung der
    # Trailing-Rendite). Das Gewicht ist daher zugunsten der FUNDAMENTALEN
    # Dominanz (ROIC, Marge, Skalengröße) reduziert — exakt die „fundamentale
    # Führerschaft", die der Score laut Design messen soll, und weitgehend
    # orthogonal zum Momentum-Cluster.
    FACTORS = (
        ("ret_3m", 0.25, False),       # Performance-Führerschaft (entkoppelt von rel_strength)
        ("roic", 0.30, False),         # Kapitalrendite-Dominanz
        ("net_margin", 0.25, False),   # Margen-Dominanz
        ("market_cap", 0.20, False),   # Größen-/Skalen-Führerschaft
    )

    def compute(self, data: InstrumentData, ctx: ScoringContext) -> ScoreResult:
        num = den = 0.0
        drivers = []
        scope_used: str | None = None

        for key, weight, invert in self.FACTORS:
            ps: PeerStat = ctx.percentile(
                data, lambda d, k=key: d.metric(k), scope="industry", invert=invert)
            if ps.percentile is None:
                continue
            scope_used = ps.scope
            num += weight * ps.percentile
            den += weight
            pct = round(ps.percentile * 100)
            if ps.percentile >= 0.8:
                drivers.append(self.pos(f"lead_{key}",
                    f"Branchenspitze bei {key} (Perzentil {pct})",
                    ps.percentile, metric=key, scope=ps.scope, n=ps.n))
            elif ps.percentile <= 0.25:
                drivers.append(self.neg(f"lag_{key}",
                    f"Nachzügler bei {key} (Perzentil {pct})",
                    1.0 - ps.percentile, metric=key, scope=ps.scope, n=ps.n))

        if den == 0:
            return self.missing("Keine Peer-Vergleichsmetriken verfügbar")

        if scope_used and scope_used != "industry":
            drivers.append(self.neu("peer_fallback",
                f"Führerschaft gegen {scope_used} bewertet (dünne Branche)",
                scope=scope_used))

        score = 10.0 * (num / den)
        state = ("Branchenführer" if score >= 7.5
                 else "Mitläufer" if score >= 4 else "Nachzügler")
        return self.result(score, state, drivers, scope=scope_used)
