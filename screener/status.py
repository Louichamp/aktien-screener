"""Status-Klassifikation: führt Score-Engine (inkl. Kronos-Intervall) und
Zonen-Engine (Konfluenzstärke) zu einem Status zusammen und stabilisiert ihn.

Zwei Stufen:
  1. `classify_candidate` — prioritätsgeordnete Kaskade -> Kandidat-Status.
  2. `TransitionValidator` — Übergangstabelle + Volumen-Validierung +
     Hysterese (Kandidat muss N Läufe bestehen), damit der Status bei
     minimalen Preisschwankungen nicht flackert.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .levels import TradePlan


class Status:
    BODEN_ABWARTEN = "Boden abwarten"
    BODENBILDUNG = "Bodenbildung"
    AUSBRUCH_VORBEREITET = "Ausbruch vorbereitet"
    BREAKOUT_AKTIV = "Breakout aktiv"
    PULLBACK_EINSTIEG = "Pullback-Einstieg"
    POSITION_VERWALTEN = "Position verwalten"
    REGRESSION_ABWARTEN = "Regression abwarten"
    DYNAMIKVERLUST = "Dynamikverlust"
    TRENDBRUCH = "Trendbruch"
    VERMEIDEN = "Vermeiden"


# Erlaubte Übergänge (struktureller Validator). Selbst-Loop immer erlaubt.
ALLOWED: dict[str, set[str]] = {
    Status.BODEN_ABWARTEN: {Status.BODENBILDUNG, Status.VERMEIDEN},
    Status.BODENBILDUNG: {Status.AUSBRUCH_VORBEREITET, Status.BODEN_ABWARTEN, Status.VERMEIDEN},
    Status.AUSBRUCH_VORBEREITET: {Status.BREAKOUT_AKTIV, Status.BODENBILDUNG, Status.BODEN_ABWARTEN},
    Status.BREAKOUT_AKTIV: {Status.POSITION_VERWALTEN, Status.REGRESSION_ABWARTEN,
                            Status.DYNAMIKVERLUST, Status.TRENDBRUCH},
    Status.PULLBACK_EINSTIEG: {Status.BREAKOUT_AKTIV, Status.POSITION_VERWALTEN, Status.TRENDBRUCH},
    Status.POSITION_VERWALTEN: {Status.PULLBACK_EINSTIEG, Status.REGRESSION_ABWARTEN,
                                Status.DYNAMIKVERLUST, Status.TRENDBRUCH},
    Status.REGRESSION_ABWARTEN: {Status.POSITION_VERWALTEN, Status.PULLBACK_EINSTIEG, Status.DYNAMIKVERLUST},
    Status.DYNAMIKVERLUST: {Status.TRENDBRUCH, Status.POSITION_VERWALTEN, Status.BODEN_ABWARTEN},
    Status.TRENDBRUCH: {Status.BODEN_ABWARTEN, Status.BODENBILDUNG, Status.VERMEIDEN},
    Status.VERMEIDEN: {Status.BODEN_ABWARTEN, Status.BODENBILDUNG},
}


@runtime_checkable
class ScoredLike(Protocol):
    """Duck-Type des ScoredInstrument aus der Score-Engine (keine harte Kopplung)."""
    technical_rating: float | None
    fundamental_rating: float | None
    total_baseline: float | None
    results: dict[str, Any]


@dataclass(slots=True)
class TechnicalState:
    """Vorberechnete technische Signale (aus der Pipeline, nicht hier gerechnet)."""
    close: float
    atr: float
    ema_50: float | None = None
    ema_200: float | None = None
    ema_50_slope: float | None = None
    ema_200_slope: float | None = None
    rsi: float | None = None
    volume_ratio: float | None = None          # heute / 50-Tage-Schnitt
    distribution_days: int = 0                 # in den letzten 25 Tagen
    avg_dollar_volume: float | None = None
    recent_breakout: bool = False              # Kurs hat jüngst Widerstandszone durchbrochen


@dataclass(slots=True)
class ClassifierInput:
    instrument_id: str
    ticker: str
    scored: ScoredLike
    plan: TradePlan
    tech: TechnicalState
    forecast: dict[str, Any] | None = None     # Kronos: mean_path, upper_band, lower_band, direction


@dataclass(slots=True)
class StatusMemory:
    """Persistierter Zustand zwischen Läufen (für Hysterese)."""
    status: str | None = None
    pending: str | None = None
    pending_count: int = 0


@dataclass(slots=True)
class Classification:
    status: str
    changed: bool
    lt_trend: str                              # up | neutral | down
    mt_trend: str
    candidate: str
    note: str | None = None
    signals: dict[str, Any] = field(default_factory=dict)
    memory: StatusMemory = field(default_factory=StatusMemory)


def _sub(scored: ScoredLike, slug: str) -> float | None:
    r = scored.results.get(slug)
    if r is None or not getattr(r, "ok", True):
        return None
    return getattr(r, "score", None)


def _trend(close: float | None, ema: float | None, slope: float | None) -> str:
    if close is None or ema is None:
        return "neutral"
    if close > ema and (slope or 0) > 0:
        return "up"
    if close < ema and (slope or 0) < 0:
        return "down"
    return "neutral"


class TransitionValidator:
    """Stabilisiert Statuswechsel: Volumen-Validierung + Hysterese + Struktur."""

    def __init__(self, confirm_runs: int = 2, breakout_volume: float = 1.4) -> None:
        self.confirm_runs = confirm_runs
        self.breakout_volume = breakout_volume

    def validate(self, memory: StatusMemory, candidate: str, *,
                 volume_ratio: float | None, hard: bool) -> tuple[StatusMemory, bool, str | None]:
        prev = memory.status
        if prev is None:                                   # Erstbewertung: Kandidat übernehmen
            return StatusMemory(candidate, None, 0), True, "Initialer Status"
        if candidate == prev:
            return StatusMemory(prev, None, 0), False, None

        # Volumen-Validierung: Breakout nur mit Volumen bestätigt
        if candidate == Status.BREAKOUT_AKTIV:
            if volume_ratio is None or volume_ratio < self.breakout_volume:
                return (StatusMemory(prev, Status.BREAKOUT_AKTIV, memory.pending_count),
                        False, "Breakout ohne Volumen – nicht bestätigt")

        # Harte Ereignisse (Disqualifikation, bestätigter Breakout) sofort
        if hard or candidate == Status.BREAKOUT_AKTIV:
            if candidate != Status.VERMEIDEN and candidate not in ALLOWED.get(prev, set()):
                return StatusMemory(prev, None, 0), False, f"Übergang {prev}→{candidate} unzulässig"
            return StatusMemory(candidate, None, 0), True, "Hartes Ereignis"

        # Struktureller Validator
        if candidate not in ALLOWED.get(prev, set()):
            return StatusMemory(prev, None, 0), False, f"Übergang {prev}→{candidate} unzulässig"

        # Hysterese: Kandidat muss confirm_runs Läufe in Folge bestehen
        count = memory.pending_count + 1 if memory.pending == candidate else 1
        if count >= self.confirm_runs:
            return StatusMemory(candidate, None, 0), True, None
        return StatusMemory(prev, candidate, count), False, "abwartend (Hysterese)"


class StatusClassifier:
    def __init__(self, validator: TransitionValidator | None = None,
                 zone_strength_min: float = 5.0, near_atr: float = 1.5,
                 ext_climax: float = 4.0, rsi_climax: float = 80.0,
                 distribution_days_roll: int = 5, liquidity_floor: float = 2_000_000.0) -> None:
        self.validator = validator or TransitionValidator()
        self.zone_strength_min = zone_strength_min
        self.near_atr = near_atr
        self.ext_climax = ext_climax
        self.rsi_climax = rsi_climax
        self.distribution_days_roll = distribution_days_roll
        self.liquidity_floor = liquidity_floor

    # ---- abgeleitete Signale --------------------------------------------
    def _signals(self, inp: ClassifierInput) -> dict[str, Any]:
        t, plan, sc = inp.tech, inp.plan, inp.scored
        atr = t.atr or 1e-9
        lt = _trend(t.close, t.ema_200, t.ema_200_slope)
        mt = _trend(t.close, t.ema_50, t.ema_50_slope)
        ext_atr = (t.close - t.ema_50) / atr if t.ema_50 else 0.0

        entry = plan.entry_zone
        near_support = bool(entry and entry.strength >= self.zone_strength_min
                            and 0 <= (t.close - entry.center) <= self.near_atr * atr)
        res_above = [z for z in plan.zones if z.kind == "resistance" and z.center > t.close]
        strong_res_near = any(z.strength >= self.zone_strength_min
                              and (z.center - t.close) <= self.near_atr * atr for z in res_above)

        setup = _sub(sc, "setup")
        base_tight = (setup is not None and setup >= 6) or (near_support and abs(ext_atr) <= 1.5)

        # Kronos-Intervall
        fc = inp.forecast or {}
        mp, lb, ub = fc.get("mean_path") or [], fc.get("lower_band") or [], fc.get("upper_band") or []
        kronos_down = (fc.get("direction") in ("down", "abwärts")
                       or (mp and mp[-1] < t.close * 0.98))
        band_width = ((ub[-1] - lb[-1]) / t.close) if (ub and lb and t.close) else None

        rolling = t.distribution_days >= self.distribution_days_roll or bool(kronos_down and mt == "up")

        risk_score = _sub(sc, "risk")                      # 10 = sicher
        risiko = (10 - risk_score) if risk_score is not None else None
        fr = sc.fundamental_rating
        disqual = bool(
            (t.avg_dollar_volume is not None and t.avg_dollar_volume < self.liquidity_floor)
            or (fr is not None and risiko is not None and fr < 2.5 and risiko >= 8)
            or (kronos_down and fr is not None and fr < 3)
        )
        return dict(lt=lt, mt=mt, ext_atr=ext_atr, near_support=near_support,
                    strong_res_near=strong_res_near, base_tight=base_tight,
                    rolling=rolling, kronos_down=kronos_down, band_width=band_width,
                    disqual=disqual, recent_breakout=t.recent_breakout)

    def classify_candidate(self, s: dict[str, Any], t: TechnicalState) -> str:
        if s["disqual"]:
            return Status.VERMEIDEN
        if s["recent_breakout"]:
            return Status.BREAKOUT_AKTIV
        if s["strong_res_near"] and s["base_tight"] and s["mt"] in ("up", "neutral"):
            return Status.AUSBRUCH_VORBEREITET
        if s["mt"] == "up" and s["rolling"]:
            return Status.DYNAMIKVERLUST
        if s["mt"] == "up" and (s["ext_atr"] >= self.ext_climax
                                or (t.rsi is not None and t.rsi >= self.rsi_climax)):
            return Status.REGRESSION_ABWARTEN
        if s["mt"] == "up" and s["near_support"]:
            return Status.PULLBACK_EINSTIEG
        if s["mt"] == "up":
            return Status.POSITION_VERWALTEN
        if s["lt"] == "up" and s["mt"] == "down":
            return Status.TRENDBRUCH
        if s["lt"] != "up" and s["base_tight"]:
            return Status.BODENBILDUNG
        return Status.BODEN_ABWARTEN

    def classify(self, inp: ClassifierInput, memory: StatusMemory | None = None) -> Classification:
        memory = memory or StatusMemory()
        sig = self._signals(inp)
        candidate = self.classify_candidate(sig, inp.tech)
        hard = candidate == Status.VERMEIDEN
        new_mem, changed, note = self.validator.validate(
            memory, candidate, volume_ratio=inp.tech.volume_ratio, hard=hard)
        return Classification(
            status=new_mem.status or candidate, changed=changed,
            lt_trend=sig["lt"], mt_trend=sig["mt"], candidate=candidate,
            note=note, signals=sig, memory=new_mem)
