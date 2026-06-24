"""Strategie-Tagging über das gesamte Universum.

Ablauf:
  1. Jede Strategie ist ein Plugin mit `eligible()` (harte Kriterien) und
     `score()` (Ranking-Kennzahl aus Scores + Kontext).
  2. Pro Strategie wird das eligible-Feld cross-sectional gerankt; das Tag
     erhält nur die Spitze (Top-X % bzw. Top-N) -> Klasse statt Masse.
  3. Ist ein Instrument in mehreren Strategien qualifiziert, entscheidet die
     höchste relative Perzentil-Dominanz über das primäre Tag.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Protocol, Type, runtime_checkable

from .status import ScoredLike


@dataclass(slots=True)
class StrategyInput:
    instrument_id: str
    ticker: str
    scored: ScoredLike
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StrategyScore:
    tag: str
    score: float
    rank: int
    n: int
    percentile: float          # 0..1, Spitze = 1.0 (Dominanz-Maß)
    qualifies: bool
    exclusivity: float = 1.0   # top_pct der Strategie (kleiner = exklusiver)


@dataclass(slots=True)
class StrategyAssignment:
    primary_tag: str | None = None
    tags: list[str] = field(default_factory=list)
    details: dict[str, StrategyScore] = field(default_factory=dict)


@runtime_checkable
class Strategy(Protocol):
    slug: str
    tag: str
    top_pct: float
    top_n: int | None

    def eligible(self, inp: StrategyInput) -> bool: ...
    def score(self, inp: StrategyInput) -> float | None: ...


class BaseStrategy(ABC):
    slug: str = ""
    tag: str = ""
    top_pct: float = 0.30
    top_n: int | None = 3

    @abstractmethod
    def eligible(self, inp: StrategyInput) -> bool: ...

    @abstractmethod
    def score(self, inp: StrategyInput) -> float | None: ...

    def sub(self, inp: StrategyInput, slug: str) -> float | None:
        r = inp.scored.results.get(slug)
        if r is None or not getattr(r, "ok", True):
            return None
        return getattr(r, "score", None)

    def feat(self, inp: StrategyInput, key: str, default: Any = None) -> Any:
        v = inp.context.get(key)
        return default if v is None else v

    @staticmethod
    def wavg(pairs: list[tuple[float, float | None]]) -> float | None:
        num = den = 0.0
        for w, v in pairs:
            if v is not None:
                num += w * v
                den += w
        return None if den == 0 else num / den


STRATEGY_REGISTRY: dict[str, Strategy] = {}


def register_strategy(cls: Type) -> Type:
    inst = cls()
    if not getattr(inst, "slug", ""):
        raise ValueError(f"{cls.__name__} hat keinen slug")
    if inst.slug in STRATEGY_REGISTRY:
        raise ValueError(f"Doppelte Strategie: {inst.slug!r}")
    if not isinstance(inst, Strategy):
        raise TypeError(f"{cls.__name__} erfüllt das Strategy-Protokoll nicht")
    STRATEGY_REGISTRY[inst.slug] = inst
    return cls


def get_strategies() -> list[Strategy]:
    return list(STRATEGY_REGISTRY.values())


@register_strategy
class GrowthStrategy(BaseStrategy):
    slug = "growth"
    tag = "WACHSTUM"
    top_pct = 0.40
    top_n = 3

    def eligible(self, inp: StrategyInput) -> bool:
        rg = self.feat(inp, "revenue_growth")
        g = self.sub(inp, "growth")
        return (rg is not None and rg >= 0.15
                and g is not None and g >= 5
                and (inp.scored.technical_rating or 0) >= 4)

    def score(self, inp: StrategyInput) -> float | None:
        return self.wavg([
            (0.40, self.sub(inp, "growth")),
            (0.18, self.sub(inp, "momentum")),
            (0.15, self.sub(inp, "rel_strength")),
            (0.12, inp.scored.technical_rating),
            (0.15, self.sub(inp, "fund_quality")),
        ])


@register_strategy
class DividendStrategy(BaseStrategy):
    slug = "dividend"
    tag = "DIVIDENDE"
    top_pct = 0.40
    top_n = 3

    def eligible(self, inp: StrategyInput) -> bool:
        dy = self.feat(inp, "dividend_yield")
        fcf = self.feat(inp, "free_cash_flow", 1.0)
        return (dy is not None and dy >= 0.025
                and fcf > 0
                and (inp.scored.fundamental_rating or 0) >= 4)

    def score(self, inp: StrategyInput) -> float | None:
        dy = self.feat(inp, "dividend_yield", 0.0)
        yield_score = max(0.0, min(10.0, dy / 0.06 * 10.0))
        return self.wavg([
            (0.30, self.sub(inp, "fund_quality")),
            (0.18, self.sub(inp, "valuation")),
            (0.20, self.sub(inp, "risk")),
            (0.32, yield_score),
        ])


@register_strategy
class CashflowStrategy(BaseStrategy):
    slug = "cashflow"
    tag = "CASHFLOW"
    top_pct = 0.40
    top_n = 3

    def eligible(self, inp: StrategyInput) -> bool:
        fm = self.feat(inp, "fcf_margin")
        fcf = self.feat(inp, "free_cash_flow", 1.0)
        fq = self.sub(inp, "fund_quality")
        return (fm is not None and fm >= 0.10
                and fcf > 0
                and fq is not None and fq >= 5)

    def score(self, inp: StrategyInput) -> float | None:
        fm = self.feat(inp, "fcf_margin", 0.0)
        fcf_score = max(0.0, min(10.0, fm / 0.25 * 10.0))
        return self.wavg([
            (0.38, self.sub(inp, "fund_quality")),
            (0.18, self.sub(inp, "valuation")),
            (0.18, self.sub(inp, "risk")),
            (0.26, fcf_score),
        ])


@register_strategy
class HiddenChampionStrategy(BaseStrategy):
    slug = "hidden_champion"
    tag = "HIDDEN CHAMPION"
    top_pct = 0.25
    top_n = 2

    def eligible(self, inp: StrategyInput) -> bool:
        mc = self.feat(inp, "market_cap")
        fq = self.sub(inp, "fund_quality")
        g = self.sub(inp, "growth")
        va = self.sub(inp, "valuation")
        ml = self.sub(inp, "market_leadership")
        return (mc is not None and 3e8 <= mc <= 1e10
                and fq is not None and fq >= 6
                and g is not None and g >= 5
                and va is not None and va >= 4
                and ml is not None and ml >= 6)

    def score(self, inp: StrategyInput) -> float | None:
        return self.wavg([
            (0.28, self.sub(inp, "fund_quality")),
            (0.24, self.sub(inp, "growth")),
            (0.20, self.sub(inp, "valuation")),
            (0.16, self.sub(inp, "market_leadership")),
            (0.12, inp.scored.fundamental_rating),
        ])


class StrategyEngine:
    def __init__(self, strategies: list[Strategy] | None = None) -> None:
        self.strategies = strategies if strategies is not None else get_strategies()

    def evaluate(self, universe: list[StrategyInput]) -> dict[str, StrategyAssignment]:
        details: dict[str, dict[str, StrategyScore]] = defaultdict(dict)

        for strat in self.strategies:
            cands = [(inp, strat.score(inp)) for inp in universe if strat.eligible(inp)]
            cands = [(inp, s) for inp, s in cands if s is not None]
            cands.sort(key=lambda x: x[1], reverse=True)
            n = len(cands)
            for rank, (inp, s) in enumerate(cands, start=1):
                percentile = 1.0 if n <= 1 else 1.0 - (rank - 1) / (n - 1)
                qualifies = (rank / n <= strat.top_pct) or (strat.top_n is not None and rank <= strat.top_n)
                details[inp.instrument_id][strat.slug] = StrategyScore(
                    tag=strat.tag, score=round(s, 2), rank=rank, n=n,
                    percentile=round(percentile, 3), qualifies=qualifies,
                    exclusivity=strat.top_pct)

        out: dict[str, StrategyAssignment] = {}
        for inp in universe:
            d = details.get(inp.instrument_id, {})
            qualifying = [ss for ss in d.values() if ss.qualifies]
            tags = [ss.tag for ss in qualifying]
            primary = None
            if qualifying:
                # Dominanz: höchstes Perzentil; bei Gleichstand die exklusivere Strategie
                best = max(qualifying, key=lambda ss: (ss.percentile, -ss.exclusivity, ss.score))
                primary = best.tag
            out[inp.instrument_id] = StrategyAssignment(primary_tag=primary, tags=tags, details=d)
        return out
