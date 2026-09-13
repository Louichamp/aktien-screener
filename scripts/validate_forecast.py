"""Hält das Prognose-Konfidenzband, was es verspricht?

Der `StatisticalForecaster` projiziert eine geometrische Brownsche Bewegung:
Drift μ und Volatilität σ aus der Historie, Band mit z·σ·√t. Das Modul heißt im
Scoring `kronos` und trägt 6 % Gewicht im `total_baseline` sowie 20 % in der
Chance-Kennzahl.

Ein Modell rechtfertigt sein Gewicht nicht dadurch, dass es existiert. Geprüft
wird deshalb (strikt Point-in-Time, dieselbe Funktion wie in Produktion):

  ABDECKUNG     Liegt der realisierte Kurs tatsächlich so oft im Band, wie das
                Band behauptet? Ein 80-%-Band, das nur 58 % der Fälle enthält,
                ist schlecht kalibriert — und ein Score, der daraus Konfidenz
                ableitet, ist es auch.
  RICHTUNG      Trifft das Vorzeichen der Prognose häufiger als eine Münze?
  FEHLER        MAE/RMSE des Mittelpfads, in Prozent vom Kurs.
  NULLMODELL    Dasselbe gegen „der Kurs bleibt, wo er ist" (Random Walk ohne
                Drift). Schlägt die Drift-Schätzung dieses Nullmodell nicht,
                liefert sie keinen Informationsgewinn.

    python scripts/validate_forecast.py --cache .cache/candles_dated_12y.pkl
"""
from __future__ import annotations

import argparse
import asyncio
import math
import os
import pickle
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from infrastructure.forecast.statistical import StatisticalForecaster
from scoring import InstrumentData, ScoringContext
from scoring.computors.kronos import ForecastComputor
from scoring.validation import build_panel_calendar
from scoring.validation.ic import ic_summary, rank_ic
from screener.pipeline import MarketSnapshot

SCORING_WINDOW = int(os.getenv("YF_KEEP_CANDLES", "260"))

# Nominale Abdeckung der z-Werte bei Normalverteilung.
Z_LEVELS = ((0.674, 0.50), (1.282, 0.80), (1.645, 0.90))


def _pct(x: float) -> str:
    return f"{x:.1%}"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(ROOT / ".cache" / "candles_dated_12y.pkl"))
    ap.add_argument("--horizon", type=int, default=30, help="Prognosehorizont in Bars")
    ap.add_argument("--step", type=int, default=42)
    ap.add_argument("--min-history", type=int, default=300)
    ap.add_argument("--limit", type=int, default=250)
    args = ap.parse_args()

    with open(args.cache, "rb") as fh:
        store = dict(list(pickle.load(fh).items())[: args.limit])
    cal = build_panel_calendar(store)
    h = args.horizon
    fc = StatisticalForecaster(horizon=h)

    inside = {lvl: 0 for _, lvl in Z_LEVELS}
    n = 0
    dir_hits = 0
    dir_n = 0
    err_model: list[float] = []
    err_naive: list[float] = []
    confidences: list[float] = []
    widths: list[float] = []
    kronos_scores: list[float] = []
    per_date: dict[int, tuple[list[float], list[float]]] = {}

    positions = cal.positions(min_history=args.min_history, horizon=h, step=args.step)
    print(f"{len(store)} Titel, {len(positions)} Stichtage, Horizont {h} Bars, "
          f"Ausrichtung {'Handelstage' if cal.dated else 'Reihenende'}\n",
          file=sys.stderr)

    for j in positions:
        for tk, candles in store.items():
            t = cal.index_at(tk, j)
            e = cal.index_at(tk, min(j + h, cal.n - 1))
            if t is None or e is None or e <= t or t < args.min_history:
                continue
            price = candles[t].c
            realised = candles[e].c
            if price <= 0 or realised <= 0:
                continue

            hist = candles[max(0, t - SCORING_WINDOW + 1): t + 1]
            snap = MarketSnapshot(instrument_id=tk, ticker=tk, price=price,
                                  candles=hist)
            out = await fc.forecast(snap, horizon=h)
            if not out or not out.get("mean_path"):
                continue

            mean_end = out["mean_path"][-1]
            n += 1
            confidences.append(float(out.get("confidence") or 0.0))

            # Abdeckung bei verschiedenen z: μ und σ aus derselben Schätzung.
            mu, sigma, _ = fc._estimate([c.c for c in hist if c.c > 0])
            for z, lvl in Z_LEVELS:
                band = z * sigma * math.sqrt(h)
                up = price * math.exp(mu * h + band)
                lo = price * math.exp(mu * h - band)
                if lo <= realised <= up:
                    inside[lvl] += 1
                if lvl == 0.80:
                    widths.append((up - lo) / price)

            # Richtung
            pred_up = mean_end >= price
            real_up = realised >= price
            dir_n += 1
            dir_hits += int(pred_up == real_up)

            # Prognosefehler, jeweils relativ zum Ausgangskurs, damit beide
            # Modelle auf derselben Skala vergleichbar sind:
            #   Modell     sagt mean_end voraus
            #   Nullmodell sagt „der Kurs bleibt bei price"
            err_model.append(abs(mean_end - realised) / price)
            err_naive.append(abs(price - realised) / price)

            # Der Score selbst — das ist die Groesse, die im Composite gewichtet
            # wird. Seine Querschnitts-Rangkorrelation zur Vorwaertsrendite ist
            # die entscheidende Zahl fuer jede Gewichtsentscheidung.
            inst = InstrumentData(instrument_id=tk, ticker=tk, asset_class="Aktie",
                                  technicals={"close": price}, fundamentals={},
                                  forecast=out)
            r = ForecastComputor().compute(inst, ScoringContext([inst], min_peers=8))
            if r.ok and not r.raw.get("missing"):
                per_date.setdefault(j, ([], []))
                per_date[j][0].append(r.score)
                per_date[j][1].append(realised / price - 1.0)
                kronos_scores.append(r.score)

    await fc.aclose()
    if n == 0:
        print("Keine auswertbaren Prognosen.", file=sys.stderr)
        return 1

    print("=" * 70)
    print(f"PROGNOSE-KALIBRIERUNG   n = {n} Prognosen, Horizont {h} Bars")
    print("=" * 70)

    print("\n1) ABDECKUNG DER KONFIDENZBAENDER")
    print(f"{'Band':<12}{'behauptet':>12}{'tatsaechlich':>15}{'Abweichung':>14}")
    print("-" * 53)
    for _z, lvl in Z_LEVELS:
        actual = inside[lvl] / n
        print(f"{_pct(lvl):<12}{_pct(lvl):>12}{_pct(actual):>15}"
              f"{actual - lvl:>+13.1%}")
    print("\n  Liegt 'tatsaechlich' deutlich unter 'behauptet', ist das Band zu")
    print("  eng — die ausgewiesene Sicherheit existiert nicht.")

    print("\n2) RICHTUNGSTREFFER")
    print(f"  {dir_hits}/{dir_n} = {_pct(dir_hits / dir_n)}  "
          f"(Muenzwurf = 50,0 %)")

    print("\n3) FEHLER DES MITTELPFADS (relativ zum realisierten Kurs)")
    mae_m = statistics.mean(err_model)
    mae_n = statistics.mean(err_naive)
    rmse_m = math.sqrt(statistics.mean(x * x for x in err_model))
    rmse_n = math.sqrt(statistics.mean(x * x for x in err_naive))
    print(f"{'Modell':<28}{'MAE':>10}{'RMSE':>10}")
    print("-" * 48)
    print(f"{'GBM (Drift + Vola)':<28}{mae_m:>9.2%}{rmse_m:>10.2%}")
    print(f"{'Nullmodell (Kurs bleibt)':<28}{mae_n:>9.2%}{rmse_n:>10.2%}")
    better = (mae_n - mae_m) / mae_n if mae_n else 0.0
    print(f"\n  Verbesserung gegenueber dem Nullmodell: {better:+.1%}")
    if better <= 0.01:
        print("  -> Die Drift-Schaetzung liefert praktisch keinen Informationsgewinn.")

    print("\n4) KONFIDENZ UND BANDBREITE (steuern das Score-Gewicht)")
    print(f"  Konfidenz: Median {statistics.median(confidences):.3f}, "
          f"Mittel {statistics.mean(confidences):.3f}, "
          f"Max {max(confidences):.3f}")
    print(f"  80-%-Bandbreite: Median {statistics.median(widths):.1%} vom Kurs")
    print("\n  Der kronos-Score rechnet score = ret_score x conf + 5 x (1 - conf).")
    low = sum(1 for c in confidences if c < 0.3) / len(confidences)
    print(f"  {low:.0%} der Prognosen haben Konfidenz < 0,30 — sie werden damit")
    print("  fast vollstaendig auf den neutralen Wert 5,0 gezogen.")

    print("\n5) VORHERSAGEKRAFT DES kronos-SCORES (die gewichtete Groesse)")
    ics = [c for j, (xs, ys) in sorted(per_date.items())
           if (c := rank_ic(xs, ys)) is not None]
    st = ic_summary("kronos", ics) if len(ics) >= 3 else None
    if st is None:
        print("  zu wenige Stichtage fuer eine IC-Schaetzung")
    else:
        print(f"  Rang-IC {st.ic_mean:+.4f}   t {st.ic_t_stat:+.2f}   "
              f"Trefferquote {st.hit_rate:.0%}   ueber {st.n_periods} Stichtage")
        print(f"  tragfaehige Kante (|t| >= 2 und Trefferquote >= 55 %): "
              f"{'JA' if st.reliable else 'NEIN'}")
    if kronos_scores:
        print(f"  Score-Verteilung: Mittel {statistics.mean(kronos_scores):.2f}, "
              f"sigma {statistics.pstdev(kronos_scores):.2f}, "
              f"Spanne {min(kronos_scores):.1f}-{max(kronos_scores):.1f}")
        print("  Eine geringe Streuung heisst: der Faktor kann keine Rangfolge")
        print("  veraendern, unabhaengig von seinem nominalen Gewicht.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
