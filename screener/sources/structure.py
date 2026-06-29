"""Struktur-Zonen: Swing-Levels mit window=5 und Konsolidierungsbereich-Erkennung."""
from __future__ import annotations

from ..zones import (BaseZoneSource, PriceLevel, ZoneCategory, ZoneContext,
                     register_zone_source, swing_points)


@register_zone_source
class StructureLevelSource(BaseZoneSource):
    """Erweiterte Swing-Struktur-Zonen (window=5, robustere Pivots als window=3)
    plus Konsolidierungsbereichs-Erkennung (8-Bar tight range < 1.5×ATR)."""
    slug = "structure"
    category = ZoneCategory.STRUCTURE

    def levels(self, ctx: ZoneContext) -> list[PriceLevel]:
        candles = ctx.candles
        if len(candles) < 12:
            return []
        out: list[PriceLevel] = []

        # Swing-Punkte mit window=5 — robustere Lokalmaxima/-minima
        highs, lows = swing_points(candles, window=5)
        for h in highs[-8:]:
            kind = "resistance" if h > ctx.price else "support"
            weight = 0.75 if abs(h - ctx.price) / ctx.price < 0.05 else 0.55
            out.append(self.lvl(h, "structure_high", weight,
                "Struktur-Hoch (robustes Widerstandsniveau)", kind))
        for l in lows[-8:]:
            kind = "support" if l < ctx.price else "resistance"
            weight = 0.75 if abs(l - ctx.price) / ctx.price < 0.05 else 0.55
            out.append(self.lvl(l, "structure_low", weight,
                "Struktur-Tief (robustes Unterstützungsniveau)", kind))

        # Konsolidierungsbereich: letzte 8 Kerzen in enger Range (< 1.5 × ATR)
        if ctx.atr > 0 and len(candles) >= 8:
            recent = candles[-8:]
            rng_high = max(c.h for c in recent)
            rng_low = min(c.l for c in recent)
            rng = rng_high - rng_low
            if rng < 1.5 * ctx.atr:
                mid = (rng_high + rng_low) / 2
                kind = "support" if mid < ctx.price else "resistance"
                out.append(self.lvl(rng_high, "consolidation_top", 0.70,
                    f"Konsolidierungsbereich oben — enge Range {rng:.2f} (ATR {ctx.atr:.2f})",
                    "resistance" if ctx.price > rng_high else "support"))
                out.append(self.lvl(rng_low, "consolidation_bot", 0.70,
                    f"Konsolidierungsbereich unten — enge Range {rng:.2f} (ATR {ctx.atr:.2f})",
                    "support" if ctx.price < rng_low else "resistance"))

        # Letztes markantes Hoch und Tief aus den vergangenen 20 Kerzen
        if len(candles) >= 20:
            last20 = candles[-20:]
            h20 = max(last20, key=lambda c: c.h)
            l20 = min(last20, key=lambda c: c.l)
            if h20.h > ctx.price:
                out.append(self.lvl(h20.h, "high_20", 0.65,
                    "20-Bar-Hoch — kurzfristiger Widerstand", "resistance"))
            if l20.l < ctx.price:
                out.append(self.lvl(l20.l, "low_20", 0.65,
                    "20-Bar-Tief — kurzfristige Unterstützung", "support"))

        return out
