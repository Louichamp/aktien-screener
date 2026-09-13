"""Walk-Forward-Backtest der SCORES — trennen höhere Scores wirklich besser?

Der vorhandene `backtest_base.py` misst TRADES (Einstieg/Stopp/Ziel eines
Ausbruchs). Dieses Skript misst die Frage davor: Sagt der Score selbst etwas
über die Zukunft — und zwar out-of-sample und über Marktphasen hinweg?

Methodik (strikt Point-in-Time, identische Funktionen wie die Produktion):
  1. An jedem Stichtag der GEMEINSAMEN Handelstagsachse
     (`scoring.validation.panel`) wird der Querschnitt mit der unveränderten
     Produktions-`ScoreEngine` bewertet — nur mit Daten ≤ Stichtag und mit
     demselben Eingangsfenster wie live (`YF_KEEP_CANDLES`).
  2. Realisierte Vorwärtsrenditen über 5 / 20 / 60 / 120 Handelstage.
  3. Zusätzlich RELATIVE Performance: gegen den Universums-Median und gegen
     den Branchen-Median desselben Stichtags. Absolute Renditen sind wegen
     Survivorship Bias nach oben verzerrt — die relative Aussage ist es
     deutlich weniger, weil die Verzerrung beide Seiten trifft.

Auswertungen:
  * IC   — Querschnitts-Rang-Korrelation je Signal und Horizont, inkl. Regime
  * KALIBRIERUNG — Score-Klassen gegen tatsächliche Vorwärtsrendite (§25)
  * SCHWELLEN — trennen die Rating-Grenzen 80/65/50/35 empirisch? (§26)
  * ABLATION — Composite ohne je einen Faktor, gegen das volle Modell (§23)
  * WALK-FORWARD — dieselben Kennzahlen je Zeitfenster (§22/§36)

GRENZEN, die nicht wegzurechnen sind:
  * Survivorship Bias: Die Kerzen-Caches enthalten nur heute noch gelistete
    Titel. Absolute Renditen sind dadurch nach oben verzerrt.
  * Keine Point-in-Time-Fundamentaldaten. Bewertet wird deshalb das
    TECHNISCHE Rating (WLATAR). Das Gesamtrating der Website (0,6·WLATAR +
    0,4·WLAFAR) ist historisch NICHT validierbar — die fundamentale Hälfte
    müsste mit Werten von heute rückwirkend eingesetzt werden.
  * Keine Handelskosten (dies misst Trennschärfe, nicht Strategierendite).

    python scripts/backtest_scores.py --cache .cache/candles_dated_12y.pkl \
        --meta-from .cache/full_snaps.pkl --step 21
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from infrastructure.providers.indicators import technicals_from_candles
from scoring import InstrumentData, ScoreEngine, ScoringContext
from scoring.composites import compose
from scoring.validation import build_panel_calendar, classify_regime
from scoring.validation.ic import ic_summary, rank_ic

SCORING_WINDOW = int(os.getenv("YF_KEEP_CANDLES", "260"))
HORIZONS = (5, 20, 60, 120)

# Nur aus Kerzen Point-in-Time rekonstruierbar.
TECHNICAL_SLUGS = ("trend", "rel_strength", "market_leadership", "momentum",
                   "volume", "institutional_demand", "breakout", "setup")

MIN_PRICE = 5.0
MIN_DOLLAR_VOL = 1_000_000.0
RETURN_CAP = 1.0            # Renditen kappen: ein Ausreißer darf nicht dominieren


# --------------------------------------------------------------------------- #
#  Beobachtung je Titel und Stichtag
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class Obs:
    date: str
    ticker: str
    industry: str | None
    scores: dict[str, float]                  # slug -> 0..10
    wlatar: float | None                      # 0..10
    fwd: dict[int, float]                     # Horizont -> absolute Rendite
    rel_universe: dict[int, float] = field(default_factory=dict)
    rel_industry: dict[int, float] = field(default_factory=dict)
    regime: str = ""


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2.0


def _liquid(candles, t: int) -> bool:
    """Gleiche Definition wie `indicators.median_dollar_volume` (60-Bar-Median)."""
    if t < 60 or candles[t].c < MIN_PRICE:
        return False
    seg = candles[t - 60:t]
    return _median([x.c * x.v for x in seg]) >= MIN_DOLLAR_VOL


# --------------------------------------------------------------------------- #
#  Durchlauf
# --------------------------------------------------------------------------- #
def collect(store: dict, meta: dict, *, step: int, min_history: int,
            window: int, limit: int | None = None) -> tuple[list[Obs], bool]:
    """Bewertet den Querschnitt an jedem Stichtag und sammelt die Ergebnisse."""
    if limit:
        store = dict(list(store.items())[:limit])
    engine = ScoreEngine()
    cal = build_panel_calendar(store)
    max_h = max(HORIZONS)
    out: list[Obs] = []

    positions = cal.positions(min_history=min_history, horizon=max_h, step=step)
    print(f"{len(store)} Titel, {cal.n} Achsenpunkte "
          f"({'Handelstage' if cal.dated else 'Rueckfall: Reihenende'}), "
          f"{len(positions)} Stichtage", file=sys.stderr, flush=True)

    for n_done, j in enumerate(positions, 1):
        insts: list[InstrumentData] = []
        rows: list[tuple[str, str | None, dict[int, float]]] = []
        regime_rows: list[dict] = []

        for tk, candles in store.items():
            t = cal.index_at(tk, j)
            if t is None or t < min_history or not _liquid(candles, t):
                continue
            price = candles[t].c
            if price <= 0:
                continue

            fwd: dict[int, float] = {}
            for h in HORIZONS:
                e = cal.index_at(tk, min(j + h, cal.n - 1))
                if e is None or e <= t:
                    continue
                r = candles[e].c / price - 1.0
                fwd[h] = max(-RETURN_CAP, min(RETURN_CAP, r))
            if not fwd:
                continue

            tech = technicals_from_candles(
                candles[max(0, t - window + 1): t + 1], price=price)
            pm = meta.get(tk, {})
            insts.append(InstrumentData(
                instrument_id=tk, ticker=tk, asset_class="Aktie",
                sector=pm.get("sector"), industry=pm.get("industry"),
                market_cap=pm.get("market_cap"), technicals=tech, fundamentals={}))
            rows.append((tk, pm.get("industry"), fwd))
            regime_rows.append({
                "realized_vol": tech.get("realized_vol"),
                "efficiency_ratio": tech.get("efficiency_ratio"),
                "above_ema200": 1.0 if (tech.get("ema_200")
                                        and price > tech["ema_200"]) else 0.0,
                "ret_1m": tech.get("ret_1m")})

        if len(insts) < 20:
            continue

        ctx = ScoringContext(insts, min_peers=engine.min_peers)
        regime = classify_regime(regime_rows).label
        label = cal.label(j)

        day: list[Obs] = []
        for inst, (tk, industry, fwd) in zip(insts, rows):
            sc = engine.score_instrument(inst, ctx)
            scores = {s: r.score for s in TECHNICAL_SLUGS
                      if (r := sc.results.get(s)) is not None
                      and r.ok and not r.raw.get("missing")}
            day.append(Obs(date=label, ticker=tk, industry=industry,
                           scores=scores, wlatar=sc.technical_rating,
                           fwd=fwd, regime=regime))

        # Relative Performance gegen Universum und Branche desselben Stichtags
        for h in HORIZONS:
            vals = [o.fwd[h] for o in day if h in o.fwd]
            if not vals:
                continue
            uni_med = _median(vals)
            by_ind: dict[str, list[float]] = defaultdict(list)
            for o in day:
                if o.industry and h in o.fwd:
                    by_ind[o.industry].append(o.fwd[h])
            ind_med = {k: _median(v) for k, v in by_ind.items() if len(v) >= 5}
            for o in day:
                if h not in o.fwd:
                    continue
                o.rel_universe[h] = o.fwd[h] - uni_med
                if o.industry in ind_med:
                    o.rel_industry[h] = o.fwd[h] - ind_med[o.industry]

        out.extend(day)
        if n_done % 10 == 0:
            print(f"  {n_done}/{len(positions)} Stichtage, "
                  f"{len(out)} Beobachtungen", file=sys.stderr, flush=True)

    return out, cal.dated


# --------------------------------------------------------------------------- #
#  Auswertungen
# --------------------------------------------------------------------------- #
def _by_date(obs: list[Obs]) -> dict[str, list[Obs]]:
    d: dict[str, list[Obs]] = defaultdict(list)
    for o in obs:
        d[o.date].append(o)
    return d


def ic_table(obs: list[Obs], *, field_name: str = "fwd") -> dict:
    """Rang-IC je Signal und Horizont (plus WLATAR als Composite)."""
    dates = _by_date(obs)
    regimes = {d: g[0].regime for d, g in dates.items()}
    series: dict[str, dict[int, list[float | None]]] = defaultdict(
        lambda: defaultdict(list))
    order = sorted(dates)

    for d in order:
        g = dates[d]
        for h in HORIZONS:
            for slug in (*TECHNICAL_SLUGS, "wlatar"):
                xs, ys = [], []
                for o in g:
                    val = o.wlatar if slug == "wlatar" else o.scores.get(slug)
                    tgt = getattr(o, field_name).get(h)
                    if val is None or tgt is None:
                        continue
                    xs.append(val)
                    ys.append(tgt)
                series[slug][h].append(rank_ic(xs, ys))

    out: dict[str, dict] = {}
    reg_list = [regimes[d] for d in order]
    for slug in (*TECHNICAL_SLUGS, "wlatar"):
        out[slug] = {}
        for h in HORIZONS:
            st = ic_summary(slug, series[slug][h], reg_list)
            if st is None:
                continue
            out[slug][h] = {"ic_mean": round(st.ic_mean, 4),
                            "t": round(st.ic_t_stat, 2),
                            "hit": round(st.hit_rate, 3),
                            "n": st.n_periods,
                            "reliable": st.reliable,
                            "by_regime": {k: round(v, 4)
                                          for k, v in st.by_regime.items()}}
    return out


BUCKETS = ((0, 20), (20, 30), (30, 40), (40, 50), (50, 60),
           (60, 70), (70, 80), (80, 90), (90, 101))


def calibration(obs: list[Obs], horizon: int) -> list[dict]:
    """Score-Klasse -> tatsächliche Vorwärtsrendite, Outperformance, Trefferquote."""
    rows = []
    for lo, hi in BUCKETS:
        sel = [o for o in obs
               if o.wlatar is not None and lo <= o.wlatar * 10 < hi
               and horizon in o.fwd]
        if len(sel) < 30:
            rows.append({"bucket": f"{lo}-{hi if hi <= 100 else 100}",
                         "n": len(sel)})
            continue
        abs_r = [o.fwd[horizon] for o in sel]
        rel_u = [o.rel_universe[horizon] for o in sel if horizon in o.rel_universe]
        rel_i = [o.rel_industry[horizon] for o in sel if horizon in o.rel_industry]
        rows.append({
            "bucket": f"{lo}-{hi if hi <= 100 else 100}",
            "n": len(sel),
            "median_return": round(_median(abs_r), 4),
            "mean_return": round(statistics.mean(abs_r), 4),
            "win_rate": round(sum(1 for x in abs_r if x > 0) / len(abs_r), 3),
            "median_vs_universe": round(_median(rel_u), 4) if rel_u else None,
            "median_vs_industry": round(_median(rel_i), 4) if rel_i else None,
        })
    return rows


RATING_EDGES = ((80, "STARK KAUFEN"), (65, "KAUFEN"), (50, "HALTEN"),
                (35, "REDUZIEREN"), (0, "VERKAUFEN"))


def rating_bands(obs: list[Obs], horizon: int) -> list[dict]:
    """Trennen die produktiven Rating-Schwellen empirisch?"""
    rows = []
    edges = list(RATING_EDGES)
    for i, (lo, name) in enumerate(edges):
        hi = edges[i - 1][0] if i > 0 else 101
        sel = [o for o in obs
               if o.wlatar is not None and lo <= o.wlatar * 10 < hi
               and horizon in o.fwd]
        if len(sel) < 30:
            rows.append({"rating": name, "range": f"{lo}-{hi}", "n": len(sel)})
            continue
        rel = [o.rel_universe[horizon] for o in sel if horizon in o.rel_universe]
        rows.append({
            "rating": name, "range": f"{lo}-{hi}", "n": len(sel),
            "median_return": round(_median([o.fwd[horizon] for o in sel]), 4),
            "median_vs_universe": round(_median(rel), 4) if rel else None,
            "win_rate": round(sum(1 for o in sel if o.fwd[horizon] > 0) / len(sel), 3),
        })
    return rows


def ablation(obs: list[Obs], weights: dict[str, float], horizon: int) -> list[dict]:
    """IC des Composites, wenn je ein Faktor entfernt wird.

    Es wird exakt `composites.compose()` verwendet — also derselbe
    Renormierungs-Mechanismus wie in der Produktion, nur mit einem Gewicht
    weniger. Gemessen wird die Veränderung des Composite-IC, nicht die
    Rendite einer Strategie.
    """
    dates = _by_date(obs)

    class _R:                      # minimaler ScoreResult-Ersatz für compose()
        __slots__ = ("score", "ok")

        def __init__(self, score: float) -> None:
            self.score, self.ok = score, True

    def composite_ic(w: dict[str, float]) -> tuple[float, float, int] | None:
        ics: list[float] = []
        for d in sorted(dates):
            xs, ys = [], []
            for o in dates[d]:
                if horizon not in o.fwd or not o.scores:
                    continue
                val = compose({s: _R(v) for s, v in o.scores.items()}, w)
                if val is None:
                    continue
                xs.append(val)
                ys.append(o.fwd[horizon])
            c = rank_ic(xs, ys)
            if c is not None:
                ics.append(c)
        if len(ics) < 3:
            return None
        st = ic_summary("x", ics)
        return (st.ic_mean, st.ic_t_stat, st.n_periods) if st else None

    full = composite_ic(weights)
    rows = [{"model": "VOLL", "ic_mean": round(full[0], 4),
             "t": round(full[1], 2), "n": full[2], "delta": 0.0}] if full else []
    if not full:
        return rows

    for slug in weights:
        reduced = {k: v for k, v in weights.items() if k != slug}
        r = composite_ic(reduced)
        if r is None:
            continue
        rows.append({"model": f"ohne {slug}", "ic_mean": round(r[0], 4),
                     "t": round(r[1], 2), "n": r[2],
                     "delta": round(r[0] - full[0], 4)})
    rows.sort(key=lambda x: x["delta"])
    return rows


def walk_forward(obs: list[Obs], horizon: int, n_folds: int = 3) -> list[dict]:
    """Dieselben Kennzahlen je Zeitfenster — ein Modell darf nicht nur in
    einer Marktphase funktionieren."""
    dates = sorted({o.date for o in obs})
    if len(dates) < n_folds * 3:
        return []
    size = len(dates) // n_folds
    rows = []
    for k in range(n_folds):
        window = set(dates[k * size: (k + 1) * size if k < n_folds - 1 else len(dates)])
        sel = [o for o in obs if o.date in window]
        ics = []
        for d in sorted(window):
            g = [o for o in sel if o.date == d]
            xs = [o.wlatar for o in g if o.wlatar is not None and horizon in o.fwd]
            ys = [o.fwd[horizon] for o in g if o.wlatar is not None and horizon in o.fwd]
            c = rank_ic(xs, ys)
            if c is not None:
                ics.append(c)
        if not ics:
            continue
        st = ic_summary("wlatar", ics)
        regs = {o.regime for o in sel}
        rows.append({"fold": k + 1,
                     "von": min(window), "bis": max(window),
                     "n_obs": len(sel),
                     "ic_mean": round(st.ic_mean, 4) if st else None,
                     "t": round(st.ic_t_stat, 2) if st else None,
                     "regime": sorted(regs)[:3]})
    return rows


# --------------------------------------------------------------------------- #
def _load_meta(path: str | None) -> dict[str, dict]:
    if not path:
        return {}
    with open(path, "rb") as fh:
        snaps = pickle.load(fh)
    return {tk: {"sector": getattr(s, "sector", None),
                 "industry": getattr(s, "industry", None),
                 "market_cap": getattr(s, "market_cap", None)}
            for tk, s in snaps.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True,
                    help="Kerzen-Cache (mehrere per Komma getrennt)")
    ap.add_argument("--meta-from", default=None,
                    help="Snapshot-Cache fuer Branche/Sektor/Marktkapitalisierung")
    ap.add_argument("--step", type=int, default=21)
    ap.add_argument("--min-history", type=int, default=300)
    ap.add_argument("--window", type=int, default=SCORING_WINDOW)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--horizon", type=int, default=60,
                    help="Leithorizont fuer Kalibrierung/Ablation/Walk-Forward")
    ap.add_argument("--out", default=None, help="Ergebnis zusaetzlich als JSON")
    args = ap.parse_args()

    store: dict = {}
    for part in args.cache.split(","):
        with open(part.strip(), "rb") as fh:
            store.update(pickle.load(fh))

    meta = _load_meta(args.meta_from)
    obs, dated = collect(store, meta, step=args.step, min_history=args.min_history,
                         window=args.window, limit=args.limit)
    if not obs:
        print("Keine Beobachtungen — Historie zu kurz?", file=sys.stderr)
        return 1

    engine = ScoreEngine()
    weights = engine.composites["technical_rating"]
    h = args.horizon
    n_dates = len({o.date for o in obs})

    print("=" * 78)
    print(f"WALK-FORWARD-SCORE-BACKTEST   {len(obs)} Beobachtungen, "
          f"{n_dates} Stichtage")
    print(f"Ausrichtung: {'echte Handelstage' if dated else 'Reihenende (kein Datum im Cache)'}"
          f" | Fenster {args.window} Bars | Leithorizont {h} Bars")
    print("=" * 78)

    # ---- 1) IC je Signal ----------------------------------------------------
    print("\n1) INFORMATION COEFFICIENT (Rang-IC gegen absolute Vorwaertsrendite)")
    print(f"{'Signal':<22}" + "".join(f"{hh:>10}d" for hh in HORIZONS))
    print("-" * 68)
    ics = ic_table(obs)
    for slug in (*TECHNICAL_SLUGS, "wlatar"):
        cells = []
        for hh in HORIZONS:
            e = ics.get(slug, {}).get(hh)
            cells.append(f"{e['ic_mean']:>+10.3f}" if e else f"{'—':>11}")
        print(f"{slug:<22}" + "".join(cells))
    print("\n  t-Werte (|t| >~ 2 = tragfaehige Kante) beim Leithorizont:")
    for slug in (*TECHNICAL_SLUGS, "wlatar"):
        e = ics.get(slug, {}).get(h)
        if e:
            flag = "  <== tragfaehig" if e["reliable"] else ""
            print(f"    {slug:<22}IC {e['ic_mean']:>+.3f}  t {e['t']:>+6.2f}  "
                  f"Trefferquote {e['hit']:.0%}{flag}")

    # ---- 2) IC gegen BRANCHEN-RELATIVE Performance --------------------------
    # Gegen den Universums-Median zu messen aendert am Querschnitts-Rang-IC
    # NICHTS: Ein fuer alle Titel desselben Stichtags gleicher Abzug laesst die
    # Rangfolge unveraendert. Nur ein GRUPPENWEISE unterschiedlicher Abzug
    # (Branchen-Median) verschiebt Raenge — nur diese Spalte traegt also
    # zusaetzliche Information.
    print("\n2) IC GEGEN BRANCHEN-RELATIVE PERFORMANCE")
    print("   (gegen den Universums-Median zu rechnen aendert einen Rang-IC")
    print("    nicht — gleicher Abzug fuer alle, gleiche Rangfolge.)")
    rel_i = ic_table(obs, field_name="rel_industry")
    print(f"\n{'Signal':<22}{'absolut':>12}{'vs Branche':>16}{'Differenz':>13}")
    print("-" * 63)

    def _cell(entry: dict | None, width: int) -> str:
        if not entry:
            return "—".rjust(width)
        return f"{entry['ic_mean']:+.3f}".rjust(width)

    for slug in (*TECHNICAL_SLUGS, "wlatar"):
        a = ics.get(slug, {}).get(h)
        i2 = rel_i.get(slug, {}).get(h)
        diff = (f"{i2['ic_mean'] - a['ic_mean']:+.3f}".rjust(13)
                if (a and i2) else "—".rjust(13))
        print(f"{slug:<22}" + _cell(a, 12) + _cell(i2, 16) + diff)

    # ---- 3) Kalibrierung, ueber ALLE Horizonte ------------------------------
    # Ein Befund, der nur auf einem Horizont auftritt, ist kein Befund. Die
    # Projekt-Historie legt nahe, dass technische Signale erst auf laengeren
    # Horizonten tragen (Ausbrueche ~12 Monate, s. breakout_signal.py).
    print("\n3) SCORE-KALIBRIERUNG (WLATAR x10) — Median-Vorwaertsrendite")
    print(f"{'Klasse':<10}{'n(60d)':>9}" + "".join(f"{hh:>10}d" for hh in HORIZONS)
          + f"{'Treffer60':>11}")
    print("-" * 73)
    cal_by_h = {hh: {r["bucket"]: r for r in calibration(obs, hh)} for hh in HORIZONS}
    for r in calibration(obs, h):
        b = r["bucket"]
        cells = []
        for hh in HORIZONS:
            e = cal_by_h[hh].get(b, {})
            cells.append(f"{e['median_return']:>+10.2%}" if "median_return" in e
                         else f"{'—':>11}")
        win = f"{r['win_rate']:>10.1%}" if "win_rate" in r else f"{'—':>11}"
        print(f"{b:<10}{r['n']:>9}" + "".join(cells) + win)

    print(f"\n   Branchenbereinigt (Horizont {h} Tage):")
    for r in calibration(obs, h):
        if r.get("median_vs_industry") is None:
            continue
        print(f"     {r['bucket']:<10}{r['n']:>8}{r['median_vs_industry']:>+10.2%}")

    # ---- 4) Rating-Schwellen ------------------------------------------------
    print("\n4) RATING-SCHWELLEN — trennen 80/65/50/35 empirisch?")
    print(f"{'Rating':<16}{'Bereich':>10}{'n':>8}"
          + "".join(f"{hh:>10}d" for hh in HORIZONS))
    print("-" * 78)
    rb_by_h = {hh: {r["rating"]: r for r in rating_bands(obs, hh)} for hh in HORIZONS}
    for r in rating_bands(obs, h):
        cells = []
        for hh in HORIZONS:
            e = rb_by_h[hh].get(r["rating"], {})
            cells.append(f"{e['median_return']:>+10.2%}" if "median_return" in e
                         else f"{'—':>11}")
        print(f"{r['rating']:<16}{r['range']:>10}{r['n']:>8}" + "".join(cells))

    # ---- 5) Ablation --------------------------------------------------------
    print(f"\n5) ABLATION — Composite-IC ohne je einen Faktor (Horizont {h})")
    print(f"{'Modell':<28}{'IC':>10}{'t':>8}{'Delta':>10}")
    print("-" * 56)
    for r in ablation(obs, weights, h):
        mark = ""
        if r["model"] != "VOLL":
            mark = "   Faktor schadet" if r["delta"] > 0.002 else (
                "   Faktor traegt bei" if r["delta"] < -0.002 else "   ohne Wirkung")
        print(f"{r['model']:<28}{r['ic_mean']:>+10.3f}{r['t']:>8.2f}"
              f"{r['delta']:>+10.3f}{mark}")
    print("\n  Delta = IC(ohne Faktor) - IC(voll). Negativ heisst: der Faktor")
    print("  traegt bei. Positiv heisst: das Modell ist ohne ihn besser.")

    # ---- 6) Walk-Forward ----------------------------------------------------
    print(f"\n6) WALK-FORWARD — WLATAR-IC je Zeitfenster (Horizont {h})")
    print(f"{'Fenster':<9}{'von':>12}{'bis':>12}{'n':>9}{'IC':>9}{'t':>8}  Regime")
    print("-" * 72)
    for r in walk_forward(obs, h):
        print(f"{r['fold']:<9}{r['von']:>12}{r['bis']:>12}{r['n_obs']:>9}"
              f"{r['ic_mean']:>+9.3f}{r['t']:>8.2f}  {', '.join(r['regime'])}")

    print("\nGRENZEN")
    print("  * Survivorship Bias: nur heute gelistete Titel -> absolute Renditen")
    print("    nach oben verzerrt. Die relativen Spalten sind belastbarer.")
    print("  * Keine Point-in-Time-Fundamentaldaten -> bewertet wird das")
    print("    TECHNISCHE Rating. Das Website-Gesamtrating (0,6 WLATAR +")
    print("    0,4 WLAFAR) ist historisch nicht validierbar.")
    print("  * Keine Handelskosten/Slippage — gemessen wird Trennschaerfe.")

    if args.out:
        Path(args.out).write_text(json.dumps({
            "n_obs": len(obs), "n_dates": n_dates, "dated": dated,
            "window": args.window, "horizon": h,
            "ic_absolute": {s: {str(k): v for k, v in d.items()} for s, d in ics.items()},
            "ic_vs_industry": {s: {str(k): v for k, v in d.items()}
                               for s, d in rel_i.items()},
            "calibration": calibration(obs, h),
            "rating_bands": rating_bands(obs, h),
            "ablation": ablation(obs, weights, h),
            "walk_forward": walk_forward(obs, h),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
