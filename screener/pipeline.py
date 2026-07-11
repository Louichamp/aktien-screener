"""Orchestraler Pipeline-Runner.

Verkettet pro Lauf den gesamten Datenfluss:
  Ingest (Snapshots + StatusMemory) ->
  Phase 1 (pro Ticker): ScoreEngine -> Zone/LevelEngine -> StatusClassifier ->
  Phase 2 (universumsweit): StrategyEngine (cross-sectional Tagging) ->
  transaktionaler Write-Back (ScreenerRow + StatusMemory) via Repository.

Hinweis: Die ScoreEngine ist intern cross-sectional (Peer-Perzentile,
Market Leadership). Daher wird der Universums-Kontext einmal vorne gebaut und
in der Per-Ticker-Schleife geteilt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from scoring import InstrumentData, ScoreEngine, ScoringContext

from .levels import LevelEngine
from .row import ScreenerRow, assemble_row
from .status import (Classification, ClassifierInput, StatusClassifier,
                     StatusMemory, TechnicalState)
from .strategies import StrategyEngine, StrategyInput
from .zones import Candle, ZoneContext


# --------------------------------------------------------------------------- #
#  Ingest-Schnittstelle
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class MarketSnapshot:
    """Rohdaten eines Instruments für einen Lauf (aus Provider oder Stub)."""
    instrument_id: str
    ticker: str
    name: str | None = None
    country: str | None = None
    as_of: str | None = None          # Zeitpunkt der Datenbeschaffung (ISO) — für Rotation/Stand
    asset_class: str = "stock"
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    currency: str | None = None
    price: float = 0.0
    technicals: dict[str, float] = field(default_factory=dict)
    fundamentals: dict[str, float] = field(default_factory=dict)
    candles: list[Candle] = field(default_factory=list)
    forecast: dict[str, Any] | None = None
    distribution_days: int = 0
    avg_dollar_volume: float | None = None
    recent_breakout: bool = False


@runtime_checkable
class MarketDataProvider(Protocol):
    async def fetch(self, ticker: str) -> MarketSnapshot | None: ...


@runtime_checkable
class RepositoryLike(Protocol):
    async def get_status_memory(self, session: Any, ticker: str) -> StatusMemory | None: ...
    async def upsert_status_memory(self, session: Any, ticker: str, memory: StatusMemory) -> None: ...
    async def upsert_screener_row(self, session: Any, values: dict[str, Any]) -> None: ...


@dataclass(slots=True)
class PipelineResult:
    rows: list[ScreenerRow] = field(default_factory=list)
    assignments: dict[str, Any] = field(default_factory=dict)
    processed: int = 0
    failed: int = 0
    errors: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
#  Assembler Snapshot -> Engine-Eingaben
# --------------------------------------------------------------------------- #
def _trend(close: float | None, ema: float | None, slope: float | None) -> str:
    if close is None or ema is None:
        return "neutral"
    if close > ema and (slope or 0) > 0:
        return "up"
    if close < ema and (slope or 0) < 0:
        return "down"
    return "neutral"


def _instrument_data(s: MarketSnapshot) -> InstrumentData:
    return InstrumentData(
        instrument_id=s.instrument_id, ticker=s.ticker, asset_class=s.asset_class,
        sector=s.sector, industry=s.industry, market_cap=s.market_cap,
        technicals=dict(s.technicals), fundamentals=dict(s.fundamentals), forecast=s.forecast)


def _zone_context(s: MarketSnapshot) -> ZoneContext:
    t = s.technicals
    return ZoneContext(
        price=s.price, atr=t.get("atr") or 1e-6, candles=s.candles,
        trend=_trend(t.get("close"), t.get("ema_200"), t.get("ema_200_slope")),
        ema_50=t.get("ema_50"), sma_200=t.get("sma_200") or t.get("ema_200"),
        forecast=s.forecast)


def _technical_state(s: MarketSnapshot) -> TechnicalState:
    t = s.technicals
    return TechnicalState(
        close=t.get("close", s.price), atr=t.get("atr") or 1e-6,
        ema_50=t.get("ema_50"), ema_200=t.get("ema_200"),
        ema_50_slope=t.get("ema_50_slope"), ema_200_slope=t.get("ema_200_slope"),
        rsi=t.get("rsi"), volume_ratio=t.get("volume_ratio"),
        distribution_days=s.distribution_days, avg_dollar_volume=s.avg_dollar_volume,
        recent_breakout=s.recent_breakout)


def _strategy_input(s: MarketSnapshot, scored: Any) -> StrategyInput:
    f = s.fundamentals
    return StrategyInput(
        instrument_id=s.instrument_id, ticker=s.ticker, scored=scored,
        context=dict(dividend_yield=f.get("dividend_yield"), market_cap=s.market_cap,
                     revenue_growth=f.get("revenue_growth"), fcf_margin=f.get("fcf_margin"),
                     free_cash_flow=f.get("free_cash_flow")))


def _driver_dict(d: Any) -> dict[str, Any]:
    return {"code": d.code, "polarity": d.polarity.value,
            "magnitude": d.magnitude, "statement": d.statement}


def _zone_dict(z: Any, *, is_entry: bool = False) -> dict[str, Any]:
    """Konfluenzzone -> serialisierbares Dict (Tearsheet / Detail-Endpunkt)."""
    return {
        "center": z.center, "low": z.low, "high": z.high,
        "strength": z.strength, "kind": z.kind,
        "categories": sorted(z.categories),
        "explain": z.explain(),
        "is_entry": is_entry,
    }


def _forecast_history(forecast: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Kronos-Forecast (mean_path/upper_band/lower_band [+ timestamps]) ->
    UI-fertige Zeitreihe list[{timestamp, mean, upper, lower}].

    Robust gegen fehlende/ungleich lange Bänder: es wird nur über die gemeinsame
    Länge gezippt; fehlt das Band, fällt es auf den Mittelpfad zurück.
    """
    if not forecast:
        return []
    mean = forecast.get("mean_path") or []
    upper = forecast.get("upper_band") or []
    lower = forecast.get("lower_band") or []
    if not mean:
        return []
    stamps = forecast.get("timestamps") or []
    out: list[dict[str, Any]] = []
    for i, m in enumerate(mean):
        if m is None:
            continue
        out.append({
            "timestamp": str(stamps[i]) if i < len(stamps) else f"t+{i + 1}",
            "mean": float(m),
            "upper": float(upper[i]) if i < len(upper) and upper[i] is not None else float(m),
            "lower": float(lower[i]) if i < len(lower) and lower[i] is not None else float(m),
        })
    return out


def _price_history(candles: list[Any], n: int = 120) -> list[float]:
    """Jüngste `n` Schlusskurse für den Verlaufs-Chart (gerundet, speicherarm)."""
    closes = [round(float(c.c), 4) for c in candles if getattr(c, "c", None)]
    return closes[-n:]


def _forecast_return(forecast: dict[str, Any] | None, price: float | None) -> float | None:
    """Erwartete Rendite bis Prognose-Ende: mean_path[-1] / Preis − 1."""
    if not forecast or not price:
        return None
    mean = forecast.get("mean_path") or []
    if not mean or mean[-1] is None:
        return None
    return round(float(mean[-1]) / price - 1.0, 4)


# Obergrenze für die je Titel gespeicherten Konfluenzzonen (JSONB-Storage-Deckel,
# siehe Timescale-Free-Tier-Kostenschätzung). Zonen sind schon nach Stärke
# sortiert -> Kappen verliert nur die schwächsten/am wenigsten relevanten.
_MAX_ZONES = 15


def _build_drivers(scored: Any, plan: Any, cls: Classification) -> dict[str, Any]:
    entry = getattr(plan, "entry_zone", None)
    ranked = sorted(plan.zones, key=lambda z: z.strength, reverse=True)
    top = ranked[:_MAX_ZONES]
    if entry is not None and entry not in top:      # Einstiegszone nie kappen
        top = top[:-1] + [entry] if top else [entry]
    return {
        "bull": [_driver_dict(d) for d in scored.bull_case(5)],
        "bear": [_driver_dict(d) for d in scored.bear_case(5)],
        "rationale": list(plan.rationale),
        "status_note": cls.note,
        # Konfluenzzonen für das Tearsheet (stärkste zuerst), Einstiegszone markiert.
        "zones": [_zone_dict(z, is_entry=(entry is not None and z is entry)) for z in top],
    }


# --------------------------------------------------------------------------- #
#  Runner
# --------------------------------------------------------------------------- #
async def run_screener_pipeline(
    tickers: list[str],
    db_session: Any,
    *,
    repository: RepositoryLike,
    provider: MarketDataProvider | None = None,
    snapshots: dict[str, MarketSnapshot] | None = None,
    score_engine: ScoreEngine | None = None,
    level_engine: LevelEngine | None = None,
    classifier: StatusClassifier | None = None,
    strategy_engine: StrategyEngine | None = None,
    currency_default: str = "USD",
    commit: bool = True,
) -> PipelineResult:
    from infrastructure.database import screener_row_to_values

    score_engine = score_engine or ScoreEngine()
    level_engine = level_engine or LevelEngine()
    classifier = classifier or StatusClassifier()
    strategy_engine = strategy_engine or StrategyEngine()
    errors: dict[str, str] = {}

    # --- Ingest: Snapshots + persistierte Hysterese laden --------------------
    snaps: dict[str, MarketSnapshot] = {}
    for tk in tickers:
        try:
            s = (snapshots or {}).get(tk)
            if s is None and provider is not None:
                s = await provider.fetch(tk)
            if s is None:
                errors[tk] = "keine Daten"
                continue
            snaps[tk] = s
        except Exception as exc:
            errors[tk] = f"ingest: {exc}"
    memories = {tk: (await repository.get_status_memory(db_session, tk) or StatusMemory())
                for tk in snaps}

    # --- Phase 1: Scoring (geteilter Kontext) + Zonen/Level + Status ----------
    instruments = [_instrument_data(s) for s in snaps.values()]
    ctx = ScoringContext(instruments, min_peers=score_engine.min_peers)
    inst_by_id = {i.instrument_id: i for i in instruments}
    per: dict[str, dict[str, Any]] = {}
    for tk, s in snaps.items():
        try:
            scored = score_engine.score_instrument(inst_by_id[s.instrument_id], ctx)
            plan = level_engine.build_plan(_zone_context(s))
            cinp = ClassifierInput(s.instrument_id, tk, scored, plan, _technical_state(s), s.forecast)
            cls = classifier.classify(cinp, memories[tk])
            per[tk] = {"scored": scored, "plan": plan, "cinp": cinp, "cls": cls, "snap": s}
        except Exception as exc:
            errors[tk] = f"phase1: {exc}"

    # --- Phase 2: universumsweites Strategie-Tagging --------------------------
    strat_inputs = [_strategy_input(d["snap"], d["scored"]) for d in per.values()]
    assignments = strategy_engine.evaluate(strat_inputs)

    # --- Write-Back: atomar (ein commit) -------------------------------------
    rows: list[ScreenerRow] = []
    for tk, d in per.items():
        scored, plan, cinp, cls, s = d["scored"], d["plan"], d["cinp"], d["cls"], d["snap"]
        assignment = assignments.get(s.instrument_id)
        row = assemble_row(cinp, cls, assignment)
        values = screener_row_to_values(
            row, price=s.price, currency=s.currency or currency_default,
            name=s.name, sector=s.sector, country=s.country, asset_class=s.asset_class,
            dividend_yield=s.fundamentals.get("dividend_yield"),
            drivers=_build_drivers(scored, plan, cls),
            forecast_history=_forecast_history(s.forecast),
            price_history=_price_history(s.candles),
            forecast_return=_forecast_return(s.forecast, s.price),
            forecast_method=(s.forecast or {}).get("method"),
            data_as_of=s.as_of)
        await repository.upsert_screener_row(db_session, values)
        await repository.upsert_status_memory(db_session, tk, cls.memory)
        rows.append(row)

    if commit:
        await db_session.commit()

    return PipelineResult(rows=rows, assignments=assignments,
                          processed=len(rows), failed=len(errors), errors=errors)
