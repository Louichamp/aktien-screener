"""Candlestick-Pattern-Zonen: bullische und bärische Umkehrsignale der letzten Kerzen."""
from __future__ import annotations

from ..zones import (BaseZoneSource, PriceLevel, ZoneCategory, ZoneContext,
                     Candle, register_zone_source)


def _body(c: Candle) -> float:
    return abs(c.c - c.o)


def _range(c: Candle) -> float:
    return c.h - c.l if c.h > c.l else 1e-9


def _upper_wick(c: Candle) -> float:
    return c.h - max(c.o, c.c)


def _lower_wick(c: Candle) -> float:
    return min(c.o, c.c) - c.l


def _is_bull(c: Candle) -> bool:
    return c.c > c.o


def _is_bear(c: Candle) -> bool:
    return c.c < c.o


def _doji(c: Candle) -> bool:
    return _body(c) <= 0.10 * _range(c)


def _marubozu_bull(c: Candle) -> bool:
    rng = _range(c)
    return _is_bull(c) and _body(c) >= 0.85 * rng and _upper_wick(c) < 0.05 * rng


def _marubozu_bear(c: Candle) -> bool:
    rng = _range(c)
    return _is_bear(c) and _body(c) >= 0.85 * rng and _lower_wick(c) < 0.05 * rng


def _hammer(c: Candle) -> bool:
    rng = _range(c)
    return (_lower_wick(c) >= 2.0 * _body(c) and
            _upper_wick(c) <= 0.20 * rng and
            _body(c) >= 0.05 * rng)


def _inverted_hammer(c: Candle) -> bool:
    rng = _range(c)
    return (_upper_wick(c) >= 2.0 * _body(c) and
            _lower_wick(c) <= 0.20 * rng and
            _body(c) >= 0.05 * rng)


def _shooting_star(c: Candle) -> bool:
    return _inverted_hammer(c) and _is_bear(c)


def _engulfing_bull(prev: Candle, curr: Candle) -> bool:
    return (_is_bear(prev) and _is_bull(curr) and
            curr.o < prev.c and curr.c > prev.o and
            _body(curr) > _body(prev))


def _engulfing_bear(prev: Candle, curr: Candle) -> bool:
    return (_is_bull(prev) and _is_bear(curr) and
            curr.o > prev.c and curr.c < prev.o and
            _body(curr) > _body(prev))


def _morning_star(a: Candle, b: Candle, c: Candle) -> bool:
    """Dreikerzen-Muster: großer Bär, kleiner Körper (Stern), großer Bulle."""
    return (_is_bear(a) and _body(a) >= 0.6 * _range(a) and
            _body(b) <= 0.30 * _body(a) and
            _is_bull(c) and _body(c) >= 0.5 * _body(a) and
            c.c > (a.o + a.c) / 2)


def _evening_star(a: Candle, b: Candle, c: Candle) -> bool:
    return (_is_bull(a) and _body(a) >= 0.6 * _range(a) and
            _body(b) <= 0.30 * _body(a) and
            _is_bear(c) and _body(c) >= 0.5 * _body(a) and
            c.c < (a.o + a.c) / 2)


def _pin_bar_bull(c: Candle) -> bool:
    rng = _range(c)
    return (_lower_wick(c) >= 0.60 * rng and
            _upper_wick(c) <= 0.15 * rng and
            _body(c) <= 0.25 * rng)


def _pin_bar_bear(c: Candle) -> bool:
    rng = _range(c)
    return (_upper_wick(c) >= 0.60 * rng and
            _lower_wick(c) <= 0.15 * rng and
            _body(c) <= 0.25 * rng)


@register_zone_source
class CandlestickPatternSource(BaseZoneSource):
    """Erkennt bullische und bärische Umkehrkerzen und gibt ihren Schlusskurs als
    Zonen-Level zurück. Schaut auf die letzten 6 Kerzen (ausreichend für 3-Kerzen-Muster)."""
    slug = "candlestick"
    category = ZoneCategory.STRUCTURE

    def levels(self, ctx: ZoneContext) -> list[PriceLevel]:
        candles = ctx.candles
        if len(candles) < 3:
            return []
        # Letzten 6 Kerzen (genug für alle Muster bis inkl. 3-Kerzen)
        recent = candles[-6:]
        out: list[PriceLevel] = []

        for i, c in enumerate(recent):
            prev = recent[i - 1] if i > 0 else None
            pprev = recent[i - 2] if i > 1 else None

            # Einzelkerzen-Muster
            if _doji(c):
                out.append(self.lvl(c.c, "doji", 0.40,
                    "Doji — Unentschlossenheit, mögliche Trendwende", "neutral"))

            if _hammer(c) and _is_bear(prev) if prev else False:
                out.append(self.lvl(c.l, "hammer", 0.65,
                    "Hammer — bullische Trendumkehr nach Abwärtsbewegung", "support"))

            if _pin_bar_bull(c):
                out.append(self.lvl(c.l, "pin_bar_bull", 0.60,
                    "Bullischer Pin Bar — starke Ablehnung der Tiefs", "support"))

            if _pin_bar_bear(c):
                out.append(self.lvl(c.h, "pin_bar_bear", 0.60,
                    "Bärischer Pin Bar — starke Ablehnung der Hochs", "resistance"))

            if _shooting_star(c) and _is_bull(prev) if prev else False:
                out.append(self.lvl(c.h, "shooting_star", 0.60,
                    "Shooting Star — bärische Trendumkehr nach Aufwärtsbewegung", "resistance"))

            if _inverted_hammer(c) and _is_bear(prev) if prev else False:
                out.append(self.lvl(c.c, "inverted_hammer", 0.45,
                    "Invertierter Hammer — mögliche bullische Trendwende", "support"))

            if _marubozu_bull(c):
                out.append(self.lvl(c.c, "marubozu_bull", 0.55,
                    "Bullischer Marubozu — starker Kaufdruck, wenig Gegendruck", "support"))

            if _marubozu_bear(c):
                out.append(self.lvl(c.c, "marubozu_bear", 0.55,
                    "Bärischer Marubozu — starker Verkaufsdruck", "resistance"))

            # Zweikerzen-Muster
            if prev is not None:
                if _engulfing_bull(prev, c):
                    out.append(self.lvl(c.c, "engulfing_bull", 0.75,
                        "Bullisches Engulfing — Käufer übernehmen Kontrolle", "support"))
                if _engulfing_bear(prev, c):
                    out.append(self.lvl(c.c, "engulfing_bear", 0.75,
                        "Bärisches Engulfing — Verkäufer übernehmen Kontrolle", "resistance"))

            # Dreikerzen-Muster
            if pprev is not None and prev is not None:
                if _morning_star(pprev, prev, c):
                    out.append(self.lvl(c.c, "morning_star", 0.80,
                        "Morning Star — starkes bullisches Umkehrsignal (3 Kerzen)", "support"))
                if _evening_star(pprev, prev, c):
                    out.append(self.lvl(c.c, "evening_star", 0.80,
                        "Evening Star — starkes bärisches Umkehrsignal (3 Kerzen)", "resistance"))

        return out
