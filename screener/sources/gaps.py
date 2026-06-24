"""Unausgefüllte Kurslücken (Gaps) als Preisniveaus."""
from __future__ import annotations

from ..zones import (BaseZoneSource, PriceLevel, ZoneCategory, ZoneContext,
                     register_zone_source)


@register_zone_source
class GapSource(BaseZoneSource):
    slug = "gap"
    category = ZoneCategory.PRICE_LEVEL

    def levels(self, ctx: ZoneContext) -> list[PriceLevel]:
        candles = ctx.candles
        out: list[PriceLevel] = []
        for prev, cur in zip(candles[-40:], candles[-39:]):
            if cur.l > prev.h:                         # Gap up -> Unterstützung an Gap-Unterkante
                edge = prev.h
                if edge < ctx.price:
                    out.append(self.lvl(edge, "gap_up", 0.5, "Aufwärts-Gap (Support)", "support"))
            elif cur.h < prev.l:                       # Gap down -> Widerstand an Gap-Oberkante
                edge = prev.l
                if edge > ctx.price:
                    out.append(self.lvl(edge, "gap_down", 0.5, "Abwärts-Gap (Widerstand)", "resistance"))
        return out
