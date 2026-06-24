"""Moving Averages als dynamische Unterstützung/Widerstand (EMA50, SMA200)."""
from __future__ import annotations

from ..zones import (BaseZoneSource, PriceLevel, ZoneCategory, ZoneContext,
                     register_zone_source)


@register_zone_source
class MovingAverageSource(BaseZoneSource):
    slug = "moving_average"
    category = ZoneCategory.MOVING_AVERAGE

    def levels(self, ctx: ZoneContext) -> list[PriceLevel]:
        out: list[PriceLevel] = []
        if ctx.ema_50:
            kind = "support" if ctx.ema_50 < ctx.price else "resistance"
            out.append(self.lvl(ctx.ema_50, "ema_50", 0.6, "EMA50", kind))
        if ctx.sma_200:
            kind = "support" if ctx.sma_200 < ctx.price else "resistance"
            out.append(self.lvl(ctx.sma_200, "sma_200", 0.8, "SMA200 (200-Tage-Linie)", kind))
        return out
