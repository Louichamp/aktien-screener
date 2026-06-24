"""Fibonacci-Retracements (Support im Aufwärtstrend) und Extensionen (Ziele)."""
from __future__ import annotations

from ..zones import BaseZoneSource, PriceLevel, ZoneCategory, ZoneContext
from ..zones import register_zone_source


@register_zone_source
class FibRetracementSource(BaseZoneSource):
    slug = "fib_retracement"
    category = ZoneCategory.FIBONACCI
    LEVELS = ((0.382, 0.6), (0.5, 0.7), (0.618, 0.9), (0.786, 0.6))

    def levels(self, ctx: ZoneContext) -> list[PriceLevel]:
        if len(ctx.candles) < 10:
            return []
        hi = max(c.h for c in ctx.candles)
        lo = min(c.l for c in ctx.candles)
        rng = hi - lo
        if rng <= 0:
            return []
        out = []
        for ratio, w in self.LEVELS:
            if ctx.trend == "down":
                price = lo + ratio * rng       # Retracement nach oben -> Widerstand
                kind = "resistance"
            else:
                price = hi - ratio * rng       # Retracement nach unten -> Support
                kind = "support"
            out.append(self.lvl(price, f"fib_{int(ratio*1000)}", w,
                                 f"Fib {ratio:.3f}-Retracement", kind))
        return out


@register_zone_source
class FibExtensionSource(BaseZoneSource):
    slug = "fib_extension"
    category = ZoneCategory.FIBONACCI
    LEVELS = ((1.272, 0.6), (1.618, 0.8))

    def levels(self, ctx: ZoneContext) -> list[PriceLevel]:
        if len(ctx.candles) < 10:
            return []
        hi = max(c.h for c in ctx.candles)
        lo = min(c.l for c in ctx.candles)
        rng = hi - lo
        if rng <= 0:
            return []
        out = []
        for ext, w in self.LEVELS:
            if ctx.trend == "down":
                price = hi - ext * rng
                kind = "support"
            else:
                price = lo + ext * rng         # Projektion über das Hoch -> Ziel/Widerstand
                kind = "resistance"
            out.append(self.lvl(price, f"fibext_{int(ext*1000)}", w,
                                 f"Fib {ext:.3f}-Extension", kind))
        return out
