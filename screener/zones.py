"""Konfluenz-Zonen-Engine.

Jede Zonen-Methode (Fibonacci, S/R, Moving Average, Volumenprofil, Gaps ...)
ist ein Plugin, das `PriceLevel`-Kandidaten liefert. Die `ZoneEngine` clustert
preislich nahe Levels zu `ConfluenceZone`s und bewertet deren Stärke:
Mehrere UNABHÄNGIGE Faktoren (verschiedene Kategorien) an derselben Stelle
ergeben eine starke Zone — mit abnehmendem Grenznutzen (Qualität > Quantität).
"""
from __future__ import annotations

import importlib
import math
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol, Type, runtime_checkable


class ZoneCategory:
    """Faktor-Kategorien (entsprechen der Trade-Rian-Systematik)."""
    FIBONACCI = "Fibonacci"
    PRICE_LEVEL = "Preisniveau"
    TREND = "Trend"
    STRUCTURE = "Struktur"
    VOLUME = "Volumen"
    DERIVATIVE = "Derivate"
    MOVING_AVERAGE = "Moving Average"


@dataclass(slots=True)
class Candle:
    o: float
    h: float
    l: float
    c: float
    v: float


@dataclass(slots=True)
class PriceLevel:
    """Ein einzelner Zonen-Kandidat einer Methode."""
    price: float
    source: str                 # z. B. "fib_0618", "ema_50", "vpoc"
    category: str               # ZoneCategory
    weight: float               # Basis-Wichtigkeit 0..1
    label: str                  # anzeigbarer Satz
    kind: str = "neutral"       # "support" | "resistance" | "neutral"


@dataclass(slots=True)
class ConfluenceZone:
    center: float
    low: float
    high: float
    strength: float                       # 0..10 (gedeckelt)
    kind: str                             # support | resistance | neutral
    members: list[PriceLevel] = field(default_factory=list)
    categories: set[str] = field(default_factory=set)

    def explain(self) -> str:
        """Kurzbegründung: welche Faktoren überlagern sich hier."""
        return " + ".join(sorted({m.source for m in self.members}))


@dataclass(slots=True)
class ZoneContext:
    """Eingabe für die Zonen-Berechnung eines Instruments."""
    price: float
    atr: float
    candles: list[Candle]
    trend: str = "neutral"                # up | down | neutral
    ema_50: float | None = None
    sma_200: float | None = None
    forecast: dict[str, Any] | None = None


# --------------------------------------------------------------------------- #
#  Plugin-Vertrag + Registry (analog zur Score-Engine)
# --------------------------------------------------------------------------- #
@runtime_checkable
class ZoneSource(Protocol):
    slug: str
    category: str

    def levels(self, ctx: ZoneContext) -> list[PriceLevel]:
        ...


class BaseZoneSource(ABC):
    slug: str = ""
    category: str = ""

    @abstractmethod
    def levels(self, ctx: ZoneContext) -> list[PriceLevel]:
        ...

    def lvl(self, price: float, source: str, weight: float, label: str,
            kind: str = "neutral") -> PriceLevel:
        return PriceLevel(price, source, self.category, weight, label, kind)


ZONE_SOURCE_REGISTRY: dict[str, ZoneSource] = {}


def register_zone_source(cls: Type) -> Type:
    inst = cls()
    slug = getattr(inst, "slug", "")
    if not slug:
        raise ValueError(f"{cls.__name__} hat keinen slug")
    if slug in ZONE_SOURCE_REGISTRY:
        raise ValueError(f"Doppelte zone-source: {slug!r}")
    if not isinstance(inst, ZoneSource):
        raise TypeError(f"{cls.__name__} erfüllt das ZoneSource-Protokoll nicht")
    ZONE_SOURCE_REGISTRY[slug] = inst
    return cls


def discover_zone_sources(package_name: str) -> None:
    pkg = importlib.import_module(package_name)
    for mod in pkgutil.iter_modules(pkg.__path__):
        if not mod.name.startswith("_"):
            importlib.import_module(f"{package_name}.{mod.name}")


def get_zone_sources() -> list[ZoneSource]:
    return list(ZONE_SOURCE_REGISTRY.values())


# --------------------------------------------------------------------------- #
#  Hilfsfunktion: Swing-Punkte (Fraktale)
# --------------------------------------------------------------------------- #
def swing_points(candles: list[Candle], window: int = 3) -> tuple[list[float], list[float]]:
    """Lokale Hochs (Widerstände) und Tiefs (Unterstützungen)."""
    highs: list[float] = []
    lows: list[float] = []
    n = len(candles)
    for i in range(window, n - window):
        seg = candles[i - window:i + window + 1]
        if candles[i].h >= max(c.h for c in seg):
            highs.append(candles[i].h)
        if candles[i].l <= min(c.l for c in seg):
            lows.append(candles[i].l)
    return highs, lows


# --------------------------------------------------------------------------- #
#  Engine
# --------------------------------------------------------------------------- #
class ZoneEngine:
    """Sammelt Levels aller Quellen und clustert sie zu Konfluenzzonen."""

    def __init__(self, sources: list[ZoneSource] | None = None,
                 band_atr: float = 0.8, band_pct: float = 0.012,
                 decay: float = 0.55, diversity_bonus: float = 0.4) -> None:
        self.sources = sources if sources is not None else get_zone_sources()
        self.band_atr = band_atr
        self.band_pct = band_pct
        self.decay = decay                  # steuert abnehmenden Grenznutzen
        self.diversity_bonus = diversity_bonus

    def collect(self, ctx: ZoneContext) -> list[PriceLevel]:
        out: list[PriceLevel] = []
        for src in self.sources:
            try:
                for lv in src.levels(ctx):
                    if lv.price and lv.price > 0:
                        out.append(lv)
            except Exception:
                continue                    # eine Quelle darf den Lauf nicht killen
        return out

    def _strength(self, members: list[PriceLevel], categories: set[str]) -> float:
        # Innerhalb einer Kategorie zählt der stärkste Faktor voll, weitere nur zu 30 %
        # -> Unabhängigkeit (verschiedene Kategorien) schlägt bloße Häufung.
        per_cat: dict[str, list[float]] = {}
        for m in members:
            per_cat.setdefault(m.category, []).append(m.weight)
        raw = 0.0
        for ws in per_cat.values():
            ws.sort(reverse=True)
            raw += ws[0] + 0.3 * sum(ws[1:])
        diversity = 1.0 + self.diversity_bonus * (len(categories) - 1)
        combined = raw * diversity
        # Soft-Cap: abnehmender Grenznutzen -> "nicht übertreiben"
        return round(10.0 * (1.0 - math.exp(-self.decay * combined)), 2)

    def cluster(self, ctx: ZoneContext, levels: list[PriceLevel]) -> list[ConfluenceZone]:
        if not levels:
            return []
        band = max(self.band_atr * ctx.atr, self.band_pct * ctx.price)
        levels = sorted(levels, key=lambda x: x.price)
        zones: list[ConfluenceZone] = []
        bucket: list[PriceLevel] = [levels[0]]

        def flush(grp: list[PriceLevel]) -> None:
            prices = [m.price for m in grp]
            wsum = sum(m.weight for m in grp) or 1.0
            center = sum(m.price * m.weight for m in grp) / wsum
            cats = {m.category for m in grp}
            kind = ("support" if center < ctx.price
                    else "resistance" if center > ctx.price else "neutral")
            zones.append(ConfluenceZone(
                center=round(center, 4), low=round(min(prices), 4),
                high=round(max(prices), 4), strength=self._strength(grp, cats),
                kind=kind, members=grp, categories=cats))

        for lv in levels[1:]:
            # Anker am ersten Mitglied: begrenzt die Zonenbreite auf ~band (kein Drift)
            if lv.price - bucket[0].price <= band:
                bucket.append(lv)
            else:
                flush(bucket)
                bucket = [lv]
        flush(bucket)
        return zones

    def compute(self, ctx: ZoneContext) -> list[ConfluenceZone]:
        zones = self.cluster(ctx, self.collect(ctx))
        return sorted(zones, key=lambda z: z.strength, reverse=True)
