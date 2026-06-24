"""Volumenprofil: VPOC und High-Volume-Nodes (Volumencluster)."""
from __future__ import annotations

from ..zones import (BaseZoneSource, PriceLevel, ZoneCategory, ZoneContext,
                     register_zone_source)


@register_zone_source
class VolumeProfileSource(BaseZoneSource):
    slug = "volume_profile"
    category = ZoneCategory.VOLUME
    BINS = 24

    def levels(self, ctx: ZoneContext) -> list[PriceLevel]:
        candles = ctx.candles
        if len(candles) < 20:
            return []
        lo = min(c.l for c in candles)
        hi = max(c.h for c in candles)
        if hi <= lo:
            return []
        width = (hi - lo) / self.BINS
        vol = [0.0] * self.BINS
        for c in candles:
            idx = min(self.BINS - 1, int((c.c - lo) / width))
            vol[idx] += c.v
        order = sorted(range(self.BINS), key=lambda i: vol[i], reverse=True)
        out: list[PriceLevel] = []
        # VPOC = stärkster Knoten
        vpoc_price = lo + (order[0] + 0.5) * width
        out.append(self.lvl(vpoc_price, "vpoc", 0.8, "VPOC (Volume Point of Control)",
                            "support" if vpoc_price < ctx.price else "resistance"))
        # weitere High-Volume-Nodes als Cluster
        for i in order[1:3]:
            price = lo + (i + 0.5) * width
            out.append(self.lvl(price, "volume_cluster", 0.55, "Volumencluster",
                                "support" if price < ctx.price else "resistance"))
        return out
