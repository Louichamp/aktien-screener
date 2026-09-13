"""Trade-Backtest der Zonen-Engine: Ablation der Quellen und echter Erwartungswert.

Der Handelsplan (`LevelEngine`) verspricht konkrete Zahlen: Einstieg an der
stärksten Support-Konfluenz, Stopp darunter, Ziel an der nächsten Widerstands-
Konfluenz, dazu ein CRV. Dieses Skript prüft, was davon trägt:

  ABLATION       Jede Zonen-Quelle einmal weggelassen. Liefert Fibonacci
                 tatsächlich Zusatznutzen, oder klingt es nur plausibel? (§14)
  DIVERSITÄT     Der Konfluenz-Bonus von +40 % je zusätzlicher Kategorie ist
                 gesetzt, nicht gemessen. Getestet über 0,0 / 0,2 / 0,4 / 0,6. (§13)
  ERWARTUNGSWERT CRV ist kein Erwartungswert. Gemessen werden P(Ziel),
                 P(Stopp), P(weder noch) und daraus EV in R-Einheiten. (§15)
  KOSTEN         Dieselben Zahlen nach Spread/Slippage/Gebühren. (§37)

Simulation (bewusst so, wie der Plan real genutzt würde):
  1. Am Stichtag t wird der Plan aus `candles[:t+1]` gebaut — Point-in-Time.
  2. Der Einstieg ist eine Limit-Order an `signal_aggr` UNTER dem Kurs. Er gilt
     nur als ausgeführt, wenn der Kurs die Zone binnen `--fill-bars` erreicht.
  3. Danach entscheidet, was ZUERST berührt wird: Stopp oder Ziel. Ein Trade,
     der erst 15 % ins Minus läuft und dann zurückkommt, ist ein Verlust.

    python scripts/backtest_zones.py --cache .cache/candles_dated_12y.pkl
"""
from __future__ import annotations

import argparse
import os
import pickle
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scoring.validation import build_panel_calendar
from screener.levels import LevelEngine
from screener.zones import ZoneContext, ZoneEngine, get_zone_sources

SCORING_WINDOW = int(os.getenv("YF_KEEP_CANDLES", "260"))
MIN_PRICE = 5.0
MIN_DOLLAR_VOL = 1_000_000.0


@dataclass(slots=True)
class Trade:
    entry: float
    stop: float
    target: float
    crv: float
    hit_target: bool
    hit_stop: bool
    r_multiple: float          # Ergebnis in Risiko-Einheiten
    mae_r: float               # groesster Buchverlust in R
    mfe_r: float               # groesster Buchgewinn in R
    zone_strength: float
    n_categories: int


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2.0


def _liquid(candles, t: int) -> bool:
    if t < 60 or candles[t].c < MIN_PRICE:
        return False
    return _median([x.c * x.v for x in candles[t - 60:t]]) >= MIN_DOLLAR_VOL


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1.0 - k)
    return e


def _atr(candles, period: int = 14) -> float | None:
    if len(candles) <= period:
        return None
    trs = []
    for i in range(1, len(candles)):
        a, b = candles[i - 1], candles[i]
        trs.append(max(b.h - b.l, abs(b.h - a.c), abs(b.l - a.c)))
    a = sum(trs[:period]) / period
    for tr in trs[period:]:
        a = (a * (period - 1) + tr) / period
    return a


def simulate(candles, t: int, plan, *, fill_bars: int, horizon: int,
             cost_pct: float) -> Trade | None:
    """Limit-Einstieg an der Zone, danach Stopp-oder-Ziel-zuerst."""
    if not (plan.signal_aggr and plan.stop_loss and plan.target_1):
        return None
    entry, stop, target = plan.signal_aggr, plan.stop_loss, plan.target_1
    if not (stop < entry < target):
        return None

    # 1) Wird die Einstiegszone ueberhaupt erreicht?
    fill = None
    for i in range(t + 1, min(t + 1 + fill_bars, len(candles))):
        if candles[i].l <= entry:
            fill = i
            break
    if fill is None:
        return None

    # Kosten: Einstieg teurer, Ausstieg billiger.
    eff_entry = entry * (1.0 + cost_pct)
    risk = eff_entry - stop
    if risk <= 0:
        return None

    hit_t = hit_s = False
    mae = mfe = 0.0
    exit_price = candles[min(fill + horizon, len(candles) - 1)].c
    for i in range(fill, min(fill + horizon + 1, len(candles))):
        c = candles[i]
        mae = min(mae, (c.l - eff_entry) / risk)
        mfe = max(mfe, (c.h - eff_entry) / risk)
        if c.l <= stop:                       # Stopp zuerst pruefen (konservativ)
            hit_s = True
            exit_price = stop * (1.0 - cost_pct)
            break
        if c.h >= target:
            hit_t = True
            exit_price = target * (1.0 - cost_pct)
            break

    r = (exit_price - eff_entry) / risk
    zone = plan.entry_zone
    return Trade(entry=eff_entry, stop=stop, target=target,
                 crv=plan.crv or 0.0, hit_target=hit_t, hit_stop=hit_s,
                 r_multiple=r, mae_r=mae, mfe_r=mfe,
                 zone_strength=zone.strength if zone else 0.0,
                 n_categories=len(zone.categories) if zone else 0)


def run(store: dict, *, sources, diversity: float, step: int, min_history: int,
        fill_bars: int, horizon: int, cost_pct: float) -> list[Trade]:
    cal = build_panel_calendar(store)
    eng = LevelEngine(zone_engine=ZoneEngine(sources=sources,
                                             diversity_bonus=diversity))
    trades: list[Trade] = []
    for j in cal.positions(min_history=min_history, horizon=horizon + fill_bars,
                           step=step):
        for tk, candles in store.items():
            t = cal.index_at(tk, j)
            if t is None or t < min_history or not _liquid(candles, t):
                continue
            hist = candles[max(0, t - SCORING_WINDOW + 1): t + 1]
            closes = [c.c for c in hist]
            price = closes[-1]
            atr = _atr(hist) or price * 0.02
            ctx = ZoneContext(price=price, atr=atr, candles=hist, trend="up",
                              ema_50=_ema(closes, 50), sma_200=_ema(closes, 200))
            try:
                plan = eng.build_plan(ctx)
            except Exception:
                continue
            tr = simulate(candles, t, plan, fill_bars=fill_bars,
                          horizon=horizon, cost_pct=cost_pct)
            if tr is not None:
                trades.append(tr)
    return trades


def stats(trades: list[Trade]) -> dict:
    if not trades:
        return {"n": 0}
    rs = [t.r_multiple for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "n": len(trades),
        "p_target": sum(t.hit_target for t in trades) / len(trades),
        "p_stop": sum(t.hit_stop for t in trades) / len(trades),
        "p_neither": sum(not t.hit_target and not t.hit_stop
                         for t in trades) / len(trades),
        "win_rate": len(wins) / len(rs),
        "avg_win": statistics.mean(wins) if wins else 0.0,
        "avg_loss": statistics.mean(losses) if losses else 0.0,
        "expectancy_r": statistics.mean(rs),
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "median_mae_r": _median([t.mae_r for t in trades]),
        "median_mfe_r": _median([t.mfe_r for t in trades]),
        "median_crv": _median([t.crv for t in trades]),
    }


def _line(name: str, s: dict) -> str:
    if not s.get("n"):
        return f"{name:<26}{'keine Trades':>12}"
    return (f"{name:<26}{s['n']:>8}{s['p_target']:>9.1%}{s['p_stop']:>9.1%}"
            f"{s['win_rate']:>9.1%}{s['expectancy_r']:>+11.3f}"
            f"{s['profit_factor']:>9.2f}")


HEAD = (f"{'Modell':<26}{'n':>8}{'P(Ziel)':>9}{'P(Stopp)':>9}"
        f"{'Treffer':>9}{'EV (R)':>11}{'PF':>9}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(ROOT / ".cache" / "candles_dated_12y.pkl"))
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--step", type=int, default=42)
    ap.add_argument("--min-history", type=int, default=300)
    ap.add_argument("--fill-bars", type=int, default=20,
                    help="Wie lange die Limit-Order an der Zone gilt")
    ap.add_argument("--horizon", type=int, default=60)
    ap.add_argument("--cost-bps", type=float, default=15.0,
                    help="Spread+Slippage+Gebuehren je Seite in Basispunkten")
    args = ap.parse_args()

    with open(args.cache, "rb") as fh:
        store = dict(list(pickle.load(fh).items())[: args.limit])
    cost = args.cost_bps / 10_000.0
    alle = get_zone_sources()
    print(f"{len(store)} Titel | Einstiegsfenster {args.fill_bars} Bars | "
          f"Horizont {args.horizon} Bars | Kosten {args.cost_bps:.0f} bp/Seite\n",
          file=sys.stderr)

    # ---- 1) Ablation der Zonen-Quellen -------------------------------------
    print("1) ABLATION DER ZONEN-QUELLEN  (je eine Quelle weggelassen)")
    print(HEAD)
    print("-" * 75)
    voll = run(store, sources=alle, diversity=0.4, step=args.step,
               min_history=args.min_history, fill_bars=args.fill_bars,
               horizon=args.horizon, cost_pct=cost)
    s_voll = stats(voll)
    print(_line("VOLL (alle Quellen)", s_voll))
    for src in alle:
        rest = [s for s in alle if s is not src]
        st = stats(run(store, sources=rest, diversity=0.4, step=args.step,
                       min_history=args.min_history, fill_bars=args.fill_bars,
                       horizon=args.horizon, cost_pct=cost))
        delta = (st.get("expectancy_r", 0.0) - s_voll.get("expectancy_r", 0.0)
                 if st.get("n") else 0.0)
        mark = ""
        if st.get("n"):
            mark = ("   Quelle schadet" if delta > 0.02 else
                    "   Quelle traegt bei" if delta < -0.02 else "   ohne Wirkung")
        print(_line(f"ohne {src.slug}", st) + mark)
    print("\n  EV in R: Erwartungswert je Trade in Risiko-Einheiten.")
    print("  Positiver Delta-Effekt heisst: ohne diese Quelle ist es besser.")

    # ---- 2) Diversitaets-Bonus ---------------------------------------------
    print("\n2) KONFLUENZ-DIVERSITAETSBONUS  (+X je zusaetzlicher Kategorie)")
    print(HEAD)
    print("-" * 75)
    for d in (0.0, 0.2, 0.4, 0.6):
        st = stats(run(store, sources=alle, diversity=d, step=args.step,
                       min_history=args.min_history, fill_bars=args.fill_bars,
                       horizon=args.horizon, cost_pct=cost))
        print(_line(f"Bonus {d:.1f}" + ("  (aktuell)" if d == 0.4 else ""), st))

    # ---- 3) Erwartungswert statt CRV ---------------------------------------
    print("\n3) CRV GEGEN TATSAECHLICHEN ERWARTUNGSWERT")
    if s_voll.get("n"):
        print(f"  ausgewiesenes CRV (Median):      {s_voll['median_crv']:>8.2f}")
        print(f"  P(Ziel zuerst):                  {s_voll['p_target']:>8.1%}")
        print(f"  P(Stopp zuerst):                 {s_voll['p_stop']:>8.1%}")
        print(f"  P(weder noch bis Horizontende):  {s_voll['p_neither']:>8.1%}")
        ev_aus_crv = (s_voll["p_target"] * s_voll["median_crv"]
                      - s_voll["p_stop"] * 1.0)
        print(f"\n  EV aus P(Ziel)xCRV - P(Stopp)x1: {ev_aus_crv:>+8.3f} R")
        print(f"  tatsaechlich gemessener EV:      {s_voll['expectancy_r']:>+8.3f} R")
        print(f"  mittlerer Gewinn / Verlust:      "
              f"{s_voll['avg_win']:>+6.2f} R / {s_voll['avg_loss']:>+6.2f} R")
        print(f"  Median MAE / MFE:                "
              f"{s_voll['median_mae_r']:>+6.2f} R / {s_voll['median_mfe_r']:>+6.2f} R")
        print("\n  Ein CRV von 3 bedeutet NICHT Erwartungswert 3 — es sagt nichts")
        print("  ueber die Wahrscheinlichkeit, das Ziel ueberhaupt zu erreichen.")

    # ---- 4) Kosten ----------------------------------------------------------
    print("\n4) WIRKUNG VON HANDELSKOSTEN")
    print(HEAD)
    print("-" * 75)
    for bps in (0.0, 5.0, 15.0, 30.0):
        st = stats(run(store, sources=alle, diversity=0.4, step=args.step,
                       min_history=args.min_history, fill_bars=args.fill_bars,
                       horizon=args.horizon, cost_pct=bps / 10_000.0))
        print(_line(f"{bps:.0f} bp je Seite", st))

    print("\nGRENZEN")
    print("  * Survivorship Bias: nur heute gelistete Titel.")
    print("  * Einstieg zum Zonenpreis angenommen (kein Teilfill, keine Luecke).")
    print("  * Keine Positionsgroessen-, Portfolio- oder Korrelationseffekte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
