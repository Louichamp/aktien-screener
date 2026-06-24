"""Klassische Preisniveaus: Swing-Hochs (Widerstand) und -Tiefs (Unterstützung)."""
from __future__ import annotations

from ..zones import (BaseZoneSource, PriceLevel, ZoneCategory, ZoneContext,
                     register_zone_source, swing_points)


@register_zone_source
class SwingLevelSource(BaseZoneSource):
    slug = "swing_sr"
    category = ZoneCategory.PRICE_LEVEL

    def levels(self, ctx: ZoneContext) -> list[PriceLevel]:
        highs, lows = swing_points(ctx.candles, window=3)
        out: list[PriceLevel] = []
        for h in highs[-6:]:
            kind = "resistance" if h > ctx.price else "support"
            out.append(self.lvl(h, "swing_high", 0.6, "Swing-Hoch (Widerstand)", kind))
        for l in lows[-6:]:
            kind = "support" if l < ctx.price else "resistance"
            out.append(self.lvl(l, "swing_low", 0.6, "Swing-Tief (Unterstützung)", kind))
        return out
