"""Universums-Kontext für die Score-Berechnung.

`InstrumentData` ist die flache Eingabe pro Instrument (TA/Fundamentals/Kronos
bereits vorberechnet aus den vorgelagerten Pipeline-Stufen). `ScoringContext`
hält die universumsweiten Strukturen, die für sektor-neutrale Normalisierung
und Peer-Gruppen (Market Leadership) gebraucht werden.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

Extractor = Callable[["InstrumentData"], "float | None"]


@dataclass(slots=True)
class InstrumentData:
    """Vorberechnete Eingangsdaten eines Instruments.

    Die Scoring-Schicht rechnet keine Indikatoren neu, sondern konsumiert
    flache Metrik-Dicts. `metric()` sucht über alle Quellen.
    """
    instrument_id: str
    ticker: str
    asset_class: str
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    technicals: dict[str, float] = field(default_factory=dict)
    fundamentals: dict[str, float] = field(default_factory=dict)
    forecast: dict[str, Any] | None = None         # Kronos: mean_path, upper_band, confidence ...
    extra: dict[str, Any] = field(default_factory=dict)

    def metric(self, key: str, default: Any = None) -> Any:
        """Flache Suche technicals -> fundamentals -> extra (None zählt als fehlend)."""
        if key == "market_cap" and self.market_cap is not None:
            return self.market_cap
        for src in (self.technicals, self.fundamentals, self.extra):
            val = src.get(key)
            if val is not None:
                return val
        return default


@dataclass(slots=True)
class PeerStat:
    """Ergebnis eines Peer-Vergleichs inkl. verwendetem Vergleichsbereich."""
    percentile: float | None           # 0..1 (bei invert bereits gedreht)
    scope: str                         # "industry" | "sector" | "universe"
    n: int


class ScoringContext:
    """Wird einmal pro Lauf aus allen Instrumenten gebaut.

    Die Engine kennt keine score-spezifischen Metriken — Computor greifen
    nur lesend über `peers()` und `percentile()` zu.
    """

    def __init__(self, instruments: list[InstrumentData], min_peers: int = 8,
                 shrink_k: float = 12.0) -> None:
        self.instruments = instruments
        self.min_peers = min_peers
        # Empirical-Bayes-Shrinkage: Stärke, mit der dünne Peer-Gruppen zur
        # neutralen Prior-Mitte (0.5) gezogen werden (größer = stärkere Dämpfung).
        self.shrink_k = shrink_k
        self._by_industry: dict[str, list[InstrumentData]] = defaultdict(list)
        self._by_sector: dict[str, list[InstrumentData]] = defaultdict(list)
        for d in instruments:
            if d.industry:
                self._by_industry[d.industry].append(d)
            if d.sector:
                self._by_sector[d.sector].append(d)

    def peers(self, data: InstrumentData, scope: str = "industry") -> tuple[list[InstrumentData], str]:
        """Peer-Gruppe mit Fallback industry -> sector -> universe.

        So bleibt Market Leadership auch in dünn besetzten Branchen robust.
        """
        if scope == "industry" and data.industry:
            grp = self._by_industry.get(data.industry, [])
            if len(grp) >= self.min_peers:
                return grp, "industry"
        if scope in ("industry", "sector") and data.sector:
            grp = self._by_sector.get(data.sector, [])
            if len(grp) >= self.min_peers:
                return grp, "sector"
        return self.instruments, "universe"

    def percentile(self, data: InstrumentData, extractor: Extractor,
                   scope: str = "industry", invert: bool = False) -> PeerStat:
        """Mid-Rank-Perzentil des Eigenwerts in der Peer-Gruppe (0..1).

        invert=True für 'kleiner ist besser' (z. B. Bewertungsmultiplikatoren).
        Liefert immer den tatsächlich verwendeten `scope` mit zurück, damit
        Computor ehrliche Driver bauen können (Transparenz bei Fallback).

        Auf das Roh-Perzentil wird eine Empirical-Bayes-Shrinkage gegen 0.5
        angewandt: bei wenigen Peers ist ein Extremwert (z. B. „Platz 1 von 3")
        statistisch unzuverlässig und wird zur neutralen Mitte gezogen
        (shrunk = 0.5 + (p − 0.5)·n/(n+k)). Bei großen n bleibt p praktisch
        unverändert. Das verhindert, dass dünne Branchen extreme Scores erzeugen.
        """
        peers, used = self.peers(data, scope)
        own = extractor(data)
        if own is None:
            return PeerStat(None, used, 0)
        vals = [v for v in (extractor(p) for p in peers) if v is not None]
        n = len(vals)
        if n < 2:
            return PeerStat(None, used, n)
        below = sum(1 for v in vals if v < own)
        equal = sum(1 for v in vals if v == own)
        pct = (below + 0.5 * equal) / n
        final = (1.0 - pct) if invert else pct
        shrunk = 0.5 + (final - 0.5) * n / (n + self.shrink_k)
        return PeerStat(shrunk, used, n)
