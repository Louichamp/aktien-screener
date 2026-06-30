"""Finales Mapping auf eine UI-fertige Datenstruktur.

`ScreenerRow` füttert die Tabellenspalten direkt: WLATAR/WLAFAR, Trend
(lang/mittel), Status, Chance, Seltenheit (aus Konfluenzstärke), Risikoklasse
(aus ATR/Stopp-Weite inkl. Kronos-Intervall), Signal- und Kursziel-Level.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .status import Classification, ClassifierInput, Status
from .strategies import StrategyAssignment

_TREND_LABEL = {"up": "AUFWÄRTS", "down": "ABWÄRTS", "neutral": "NEUTRAL"}

# Chance-Deckelung je Status (handelbar = volle Chance)
_CHANCE_CAP = {
    Status.AUSBRUCH_VORBEREITET: 10.0, Status.BREAKOUT_AKTIV: 10.0,
    Status.PULLBACK_EINSTIEG: 10.0, Status.BODENBILDUNG: 10.0,
    Status.POSITION_VERWALTEN: 4.0, Status.REGRESSION_ABWARTEN: 4.0,
    Status.DYNAMIKVERLUST: 2.0, Status.TRENDBRUCH: 2.0,
    Status.BODEN_ABWARTEN: 2.0, Status.VERMEIDEN: 1.0,
}


@dataclass(slots=True)
class ScreenerRow:
    instrument_id: str
    ticker: str
    # Headline-Ratings
    wlatar: float | None                 # Technical Rating 0..10
    wlafar: float | None                 # Fundamental Rating 0..10
    total: float | None                  # Gesamt 0..100
    # Trend
    trend_long: str                      # AUFWÄRTS | NEUTRAL | ABWÄRTS
    trend_mid: str
    # Zustand & Chance
    status: str
    status_changed: bool
    chance: float                        # 0..10
    chance_dots: int                     # 0..5 (UI-Punkte)
    rarity: str                          # Seltenheit der Chance
    rarity_strength: float               # zugrunde liegende Konfluenzstärke
    # Risiko
    risk_class: str                      # Risikoklasse-Label
    risk_level: int                      # 1..5
    # Handelbare Level
    signal_aggr: float | None
    signal_kons: float | None
    stop_loss: float | None
    target_1: float | None
    target_2: float | None
    crv: float | None
    rationale: list[str] = field(default_factory=list)
    # Strategie-Tagging
    strategy_tag: str | None = None              # primäres Tag (Spalte "Strategie")
    strategy_tags: list[str] = field(default_factory=list)   # alle qualifizierten Tags


def _crv_score(crv: float | None) -> float | None:
    if crv is None:
        return None
    pts = [(0.0, 0.0), (1.0, 2.0), (1.5, 4.0), (2.0, 6.0), (3.0, 8.0), (4.0, 10.0)]
    if crv <= pts[0][0]:
        return pts[0][1]
    if crv >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= crv <= x1:
            return y0 + (y1 - y0) * (crv - x0) / (x1 - x0)
    return pts[-1][1]


def _sub_score(sc: Any, slug: str) -> float | None:
    """Sub-Score nur, wenn vorhanden UND fehlerfrei (ok). Fehlende Signale
    werden aus der Chance-Mischung ausgelassen (num/den renormiert), statt mit
    einem Phantom-5.0 einzufließen — konsistent zur compose()/missing()-Logik."""
    r = sc.results.get(slug)
    if r is None or not getattr(r, "ok", True):
        return None
    return getattr(r, "score", None)


def _compute_chance(inp: ClassifierInput, status: str) -> float:
    sc, plan = inp.scored, inp.plan
    setup = _sub_score(sc, "setup")
    kronos = _sub_score(sc, "kronos")
    terms = [(0.30, setup), (0.25, _crv_score(plan.crv)),
             (0.25, sc.technical_rating), (0.20, kronos)]
    num = den = 0.0
    for w, v in terms:
        if v is not None:
            num += w * v
            den += w
    raw = (num / den) if den else 0.0
    return round(min(raw, _CHANCE_CAP.get(status, 10.0)), 2)


def _rarity(strength: float) -> str:
    if strength >= 8.5:
        return "sehr selten"
    if strength >= 7.0:
        return "selten"
    if strength >= 5.0:
        return "gelegentlich"
    if strength >= 3.0:
        return "häufig"
    return "alltäglich"


def _risk_class(inp: ClassifierInput) -> tuple[str, int]:
    """Risikoklasse aus Stopp-Weite (bzw. ATR%) plus Kronos-Unsicherheit."""
    t, plan = inp.tech, inp.plan
    if plan.signal_aggr and plan.stop_loss and plan.signal_aggr > 0:
        width = (plan.signal_aggr - plan.stop_loss) / plan.signal_aggr
    elif t.close:
        width = t.atr / t.close
    else:
        width = 0.0
    fc = inp.forecast or {}
    ub, lb = fc.get("upper_band") or [], fc.get("lower_band") or []
    if ub and lb and t.close:
        band = (ub[-1] - lb[-1]) / t.close            # Kronos-Intervallbreite
        width = max(width, 0.6 * width + 0.4 * band)  # Unsicherheit weitet das Risiko
    bands = [(0.02, "sehr niedrig", 1), (0.04, "niedrig", 2),
             (0.06, "mittel", 3), (0.09, "hoch", 4)]
    for thr, label, lvl in bands:
        if width < thr:
            return label, lvl
    return "sehr hoch", 5


def assemble_row(inp: ClassifierInput, cls: Classification,
                 assignment: StrategyAssignment | None = None) -> ScreenerRow:
    sc, plan = inp.scored, inp.plan
    strength = (plan.entry_zone.strength if plan.entry_zone
                else max((z.strength for z in plan.zones), default=0.0))
    chance = _compute_chance(inp, cls.status)
    risk_label, risk_lvl = _risk_class(inp)
    rationale = list(plan.rationale)
    if cls.note:
        rationale.append(f"Status: {cls.note}")
    return ScreenerRow(
        instrument_id=inp.instrument_id, ticker=inp.ticker,
        wlatar=sc.technical_rating, wlafar=sc.fundamental_rating, total=sc.total_baseline,
        trend_long=_TREND_LABEL[cls.lt_trend], trend_mid=_TREND_LABEL[cls.mt_trend],
        status=cls.status, status_changed=cls.changed,
        chance=chance, chance_dots=round(chance / 2),
        rarity=_rarity(strength), rarity_strength=strength,
        risk_class=risk_label, risk_level=risk_lvl,
        signal_aggr=plan.signal_aggr, signal_kons=plan.signal_kons,
        stop_loss=plan.stop_loss, target_1=plan.target_1, target_2=plan.target_2,
        crv=plan.crv, rationale=rationale,
        strategy_tag=assignment.primary_tag if assignment else None,
        strategy_tags=list(assignment.tags) if assignment else [],
    )
