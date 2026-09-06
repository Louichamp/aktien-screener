"""Audit des Scoring-Systems auf echten Querschnittsdaten.

Beantwortet die Fragen, die eine Gewichtstabelle NICHT beantwortet:

  * Welcher Faktor beeinflusst das Ranking tatsächlich — und wie stark?
    Das nominale Gewicht sagt das nicht. Ein Faktor, bei dem im Querschnitt
    alle Titel nahe 7/10 liegen, kann 20 % Gewicht haben und trotzdem keine
    einzige Rangfolge verändern. Maßgeblich ist Gewicht × Streuung.
  * Messen mehrere Faktoren dasselbe? Drei Varianten derselben Trendaussage
    dürfen nicht dreifach zählen.
  * Kann ein einzelner Extremwert den Gesamtscore kippen?
  * Werden fehlende Faktoren korrekt behandelt (ausgeschlossen statt geraten)?

Datengrundlage sind gecachte Kurshistorien; bewertet werden daher die
TECHNISCHEN Faktoren. Die fundamentalen brauchen Point-in-Time-Fundamentaldaten,
die hier nicht vorliegen — das wird ausgewiesen, nicht überspielt.

    python scripts/audit_scores.py --cache .cache/backtest_candles_12y.pkl
"""
from __future__ import annotations

import argparse
import pickle
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from infrastructure.providers.indicators import technicals_from_candles
from scoring import InstrumentData, ScoreEngine, ScoringContext
from scoring.validation.orthogonality import (_rank_corr, correlation_matrix,
                                              redundancy_report)

SECTORS = ["Technology", "Healthcare", "Financials", "Energy", "Consumer",
           "Industrials", "Utilities", "Materials"]


def build_panel(store: dict, limit: int):
    """Querschnitt zu EINEM Zeitpunkt (letzter Bar) — so wie die Engine live läuft."""
    insts = []
    for i, (tk, candles) in enumerate(list(store.items())[:limit]):
        if len(candles) < 260:
            continue
        c = candles[-400:]
        price = c[-1].c
        if price <= 0:
            continue
        insts.append(InstrumentData(
            instrument_id=tk, ticker=tk, asset_class="Aktie",
            sector=SECTORS[i % len(SECTORS)], industry=None, market_cap=1e9,
            technicals=technicals_from_candles(c, price=price), fundamentals={}))
    engine = ScoreEngine()
    ctx = ScoringContext(insts, min_peers=engine.min_peers)
    scored = {i.instrument_id: engine.score_instrument(i, ctx) for i in insts}
    return engine, insts, scored


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(ROOT / ".cache" / "backtest_candles_12y.pkl"))
    ap.add_argument("--limit", type=int, default=400)
    args = ap.parse_args()

    with open(args.cache, "rb") as fh:
        store = pickle.load(fh)
    engine, insts, scored = build_panel(store, args.limit)
    print(f"Querschnitt: {len(insts)} Titel aus {Path(args.cache).name}\n")

    weights = engine.composites["technical_rating"]
    slugs = list(weights)

    # ---- 1) Verfügbarkeit und Streuung je Faktor ---------------------------
    vals: dict[str, list[float]] = {s: [] for s in slugs}
    panel: list[dict[str, float]] = []
    for sc in scored.values():
        row = {}
        for s in slugs:
            r = sc.results.get(s)
            if r is not None and getattr(r, "ok", False):
                vals[s].append(r.score)
                row[s] = r.score
        panel.append(row)

    influence = {}
    for s in slugs:
        v = vals[s]
        influence[s] = weights[s] * statistics.pstdev(v) if len(v) >= 5 else 0.0
    total_inf = sum(influence.values()) or 1.0

    print("FAKTOR-EINFLUSS  (das nominale Gewicht sagt wenig — es zaehlt Gewicht x Streuung)")
    print(f"{'Faktor':<22}{'Gew.':>7}{'verfueg':>9}{'Mittel':>8}{'StdAbw':>8}"
          f"{'Einfluss':>10}{'realer Anteil':>15}")
    print("-" * 79)
    for s in sorted(slugs, key=lambda x: -influence[x]):
        v = vals[s]
        if len(v) < 5:
            print(f"{s:<22}{weights[s]:>7.2f}{len(v):>9}   zu wenig Daten")
            continue
        print(f"{s:<22}{weights[s]:>7.2f}{len(v)/len(insts):>8.0%}"
              f"{statistics.mean(v):>8.2f}{statistics.pstdev(v):>8.2f}"
              f"{influence[s]:>10.3f}{influence[s]/total_inf:>14.1%}")
    print("\n  Weicht der reale Anteil stark vom Gewicht ab, ist die Gewichtung")
    print("  nicht das, was sie zu sein vorgibt.")

    # ---- 2) Redundanz -------------------------------------------------------
    rep = redundancy_report(panel, slugs, threshold=0.7)
    corr = correlation_matrix(panel, slugs)
    print(f"\n\nREDUNDANZ  —  {rep['n_signals']} Faktoren, effektiv nur "
          f"{rep['effective_signals']} unabhaengige")
    if rep["clusters"]:
        print("  Cluster (paarweise |Korrelation| >= 0,70):")
        for c in rep["clusters"]:
            print("    " + " + ".join(c))
    else:
        print("  Keine Cluster ueber Schwellwert 0,70.")
    print("\n  Staerkste Paare:")
    for (a, b), c in sorted(corr.items(), key=lambda kv: -abs(kv[1]))[:8]:
        tag = "   (gegenlaeufig)" if c < 0 else ""
        print(f"    {abs(c):>5.2f}  {a} <-> {b}{tag}")

    # ---- 3) Extremwert-Empfindlichkeit -------------------------------------
    tw = sum(weights.values())
    print("\n\nEXTREMWERT-EMPFINDLICHKEIT")
    print("  Wie weit bewegt EIN Faktor von 0 auf 10 das technische Rating?")
    print(f"{'Faktor':<22}{'Gew.':>7}{'max. Hub (0-10)':>18}{'in Punkten 0-100':>19}")
    print("-" * 66)
    for s in sorted(slugs, key=lambda x: -weights[x]):
        hub = weights[s] / tw * 10.0
        print(f"{s:<22}{weights[s]:>7.2f}{hub:>17.2f}{hub*10:>18.1f}")

    # ---- 4) Fehlende Faktoren ----------------------------------------------
    cov = [len(row) / len(slugs) for row in panel]
    n_missing = sum(1 for row in panel if len(row) < len(slugs))
    print("\n\nUMGANG MIT FEHLENDEN FAKTOREN")
    print(f"  Titel mit mindestens einem fehlenden Faktor: {n_missing}/{len(panel)}")
    print(f"  Mittlere Faktor-Abdeckung: {statistics.mean(cov):.1%}")
    print("  Fehlende Faktoren werden ausgeschlossen und die Gewichte renormiert")
    print("  (composites.compose) — es wird NICHT mit einem Mittelwert aufgefuellt.")
    print("  Unter 30 % Abdeckung faellt der Score ganz weg (MIN_COVERAGE).")

    # ---- 5) Korrelation Faktor <-> Gesamtergebnis --------------------------
    print("\n\nKORRELATION FAKTOR <-> TECHNISCHES RATING")
    rows = []
    for s in slugs:
        xs, ys = [], []
        for tk, sc in scored.items():
            r = sc.results.get(s)
            if r is not None and getattr(r, "ok", False) and sc.technical_rating is not None:
                xs.append(r.score)
                ys.append(sc.technical_rating)
        c = _rank_corr(xs, ys)
        if c is not None:
            rows.append((c, s))
    print(f"{'Faktor':<22}{'Rang-Korr.':>12}")
    print("-" * 34)
    for c, s in sorted(rows, reverse=True):
        print(f"{s:<22}{c:>12.2f}")

    print("\n\nGRENZE DIESER ANALYSE")
    print("  Bewertet sind nur die TECHNISCHEN Faktoren. Die fundamentalen")
    print("  (fund_quality, growth, valuation) brauchen Point-in-Time-")
    print("  Fundamentaldaten, die hier nicht vorliegen — sie sind in dieser")
    print("  Auswertung NICHT enthalten und bleiben ungeprueft.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
