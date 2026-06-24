"""Ableitung der handelbaren Level aus Konfluenzzonen.

Der Einstieg wird an der stärksten Support-Konfluenz nahe dem Kurs verankert,
der Stopp unter deren Unterkante, die Ziele an den nächsten Widerstands-
Konfluenzen — jeweils gegen die Kronos-Prognose plausibilisiert. Jede Zahl
trägt ihre Konfluenz-Begründung mit (für die "Signal"-/"Kursziel"-Spalten).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .zones import ConfluenceZone, ZoneContext, ZoneEngine


@dataclass(slots=True)
class TradePlan:
    signal_aggr: float | None = None       # früher Einstieg (an der Zone)
    signal_kons: float | None = None       # bestätigter Einstieg (Reclaim)
    stop_loss: float | None = None
    target_1: float | None = None          # Kursziel 1
    target_2: float | None = None          # Kursziel 2
    crv: float | None = None               # Chance-Risiko-Verhältnis
    entry_zone: ConfluenceZone | None = None
    rationale: list[str] = field(default_factory=list)
    zones: list[ConfluenceZone] = field(default_factory=list)


class LevelEngine:
    def __init__(self, zone_engine: ZoneEngine | None = None,
                 max_entry_dist_atr: float = 3.0, stop_buffer_atr: float = 0.5,
                 max_risk_pct: float = 0.08) -> None:
        self.zones = zone_engine or ZoneEngine()
        self.max_entry_dist_atr = max_entry_dist_atr
        self.stop_buffer_atr = stop_buffer_atr
        self.max_risk_pct = max_risk_pct

    def build_plan(self, ctx: ZoneContext) -> TradePlan:
        zones = self.zones.compute(ctx)
        plan = TradePlan(zones=zones)
        if not zones:
            return plan

        supports = [z for z in zones if z.center < ctx.price]
        resistances = sorted((z for z in zones if z.center > ctx.price),
                             key=lambda z: z.center)

        # Einstiegszone = stärkste Support-Konfluenz in erreichbarer Nähe
        reachable = [z for z in supports
                     if (ctx.price - z.center) <= self.max_entry_dist_atr * ctx.atr]
        entry = max(reachable, key=lambda z: z.strength) if reachable else None
        if entry is None:
            entry = max(supports, key=lambda z: z.strength) if supports else None

        if entry is not None:
            plan.entry_zone = entry
            plan.signal_aggr = round(entry.center, 2)
            plan.signal_kons = round(entry.high * 1.005, 2)        # Reclaim über die Zone
            stop = entry.low - self.stop_buffer_atr * ctx.atr
            stop = max(stop, plan.signal_aggr * (1 - self.max_risk_pct))  # Risiko-Cap 8 %
            plan.stop_loss = round(stop, 2)
            plan.rationale.append(
                f"Einstieg an Konfluenzzone (Stärke {entry.strength}): {entry.explain()}")

        # Ziele aus Widerstands-Konfluenzen, gegen Kronos plausibilisiert
        kronos_mean = kronos_upper = None
        if ctx.forecast:
            mp = ctx.forecast.get("mean_path") or []
            ub = ctx.forecast.get("upper_band") or []
            kronos_mean = mp[-1] if mp else None
            kronos_upper = ub[-1] if ub else None

        if resistances:
            t1 = resistances[0]
            plan.target_1 = round(min(t1.center, kronos_mean) if kronos_mean else t1.center, 2)
            plan.rationale.append(f"Kursziel 1 an Widerstand: {t1.explain()}")
            if len(resistances) > 1:
                t2 = resistances[1]
                plan.target_2 = round(max(t2.center, kronos_upper) if kronos_upper else t2.center, 2)
                plan.rationale.append(f"Kursziel 2 an Widerstand: {t2.explain()}")
            elif kronos_upper:
                plan.target_2 = round(kronos_upper, 2)
                plan.rationale.append("Kursziel 2 aus oberem Kronos-Konfidenzband")

        # CRV
        if plan.signal_aggr and plan.stop_loss and plan.target_1:
            risk = plan.signal_aggr - plan.stop_loss
            reward = plan.target_1 - plan.signal_aggr
            if risk > 0:
                plan.crv = round(reward / risk, 2)
        return plan
