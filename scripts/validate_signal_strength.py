"""Hält die Signalstärke, was sie verspricht?

Die Einstufung stark/moderat/schwach ist eine Behauptung über Qualität. Dieses
Skript prüft sie an der Historie: An monatlichen Stichtagen wird der komplette
Querschnitt bewertet — ausschließlich mit Daten, die zum Stichtag vorlagen —
und anschließend gemessen, wie sich die Titel je Stufe tatsächlich entwickelt
haben.

Strikt point-in-time:
  * Zum Stichtag t sehen Indikatoren und Score nur candles[:t+1].
  * Die Vorwärtsrendite stammt aus t+h und fließt nirgends in die Bewertung.
  * Der Querschnitt (Peer-Perzentile, Market Leadership) wird je Stichtag neu
    aus genau den Titeln gebaut, die zu diesem Zeitpunkt Historie hatten.

Bekannte Grenzen, die das Ergebnis einschränken und NICHT wegzurechnen sind:
  * Survivorship Bias — die Kerzen-Caches enthalten nur heute noch gelistete
    Titel. Zwischenzeitlich delistete fehlen, was jede Auswertung nach oben
    verzerrt. Das ist eine Eigenschaft der Datenquelle, keine Wahl.
  * Keine Fundamentaldaten mit Zeitstempel, daher nur technische Faktoren.
  * Keine Handelskosten, kein Slippage — gemessen wird die Trennschärfe der
    Einstufung, nicht die Rendite einer Strategie.

    python scripts/validate_signal_strength.py --cache .cache/smallcap_12y.pkl
"""
from __future__ import annotations

import argparse
import os
import pickle
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from infrastructure.providers.indicators import technicals_from_candles
from scoring import InstrumentData, ScoreEngine, ScoringContext
from scoring.validation import build_panel_calendar
from screener.explain import SignalStrength, build_breakdown

# Eingangsfenster wie in Produktion (YF_KEEP_CANDLES); vorher fest 400 Bars.
SCORING_WINDOW = int(os.getenv("YF_KEEP_CANDLES", "260"))
ORDER = [SignalStrength.STRONG, SignalStrength.MODERATE,
         SignalStrength.WEAK, SignalStrength.NONE]

MIN_PRICE = 5.0
MIN_DOLLAR_VOL = 1_000_000.0
CAP = 1.0                       # Renditen kappen — ein Ausreißer darf nicht dominieren


def _load_peer_meta(path: str | None) -> dict[str, dict]:
    """Echte Branche/Sektor/Marktkapitalisierung je Ticker.

    Frueher wurden hier Platzhalter gesetzt (Sektor per Round-Robin,
    market_cap konstant 1e9). Dadurch verlor `market_leadership` drei seiner
    vier Faktoren und reduzierte sich auf ret_3m — die Hauptkomponente von
    `rel_strength`. Die daraus gemessene Korrelation zwischen beiden war ein
    Artefakt der Messbedingungen.
    """
    if not path:
        return {}
    try:
        with open(path, "rb") as fh:
            snaps = pickle.load(fh)
    except (OSError, ValueError, pickle.UnpicklingError) as exc:
        print(f"Peer-Kontext nicht lesbar ({exc}) — ohne Branchenangaben.")
        return {}
    return {tk: {"sector": getattr(s, "sector", None),
                 "industry": getattr(s, "industry", None),
                 "market_cap": getattr(s, "market_cap", None)}
            for tk, s in snaps.items()}


def _liquid(candles, t: int) -> bool:
    if t < 60 or candles[t].c < MIN_PRICE:
        return False
    seg = candles[t - 60:t]
    return statistics.median(x.c * x.v for x in seg) >= MIN_DOLLAR_VOL


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(ROOT / ".cache" / "smallcap_12y.pkl"))
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--step", type=int, default=21, help="Bar-Abstand der Stichtage")
    ap.add_argument("--min-history", type=int, default=300)
    ap.add_argument("--horizons", default="5,20,60")
    ap.add_argument("--meta-from", default=None,
                    help="Snapshot-Cache (z.B. .cache/full_snaps.pkl) fuer echte "
                         "Branche/Sektor/Marktkapitalisierung statt Platzhalter")
    args = ap.parse_args()

    horizons = [int(h) for h in args.horizons.split(",")]
    max_h = max(horizons)

    with open(args.cache, "rb") as fh:
        store = {k: v for k, v in list(pickle.load(fh).items())[: args.limit]
                 if len(v) >= args.min_history + max_h}
    print(f"{len(store)} Titel aus {Path(args.cache).name}, "
          f"Stichtage alle {args.step} Bars\n")

    engine = ScoreEngine()
    meta_map = _load_peer_meta(args.meta_from)
    cal = build_panel_calendar(store)
    if not cal.dated:
        print("WARNUNG: Kerzen ohne Datum — Ausrichtung vom Reihenende statt "
              "nach Handelstag.\n")
    have_peers = sum(1 for tk in store if meta_map.get(tk, {}).get("industry")
                     or meta_map.get(tk, {}).get("sector"))
    if not have_peers:
        print("WARNUNG: kein echter Branchen-/Sektor-Kontext (--meta-from). "
              "Alle Peer-Perzentile fallen auf 'universe' zurueck; "
              "rel_strength/market_leadership messen dann NICHT das "
              "Produktionsverhalten.\n")

    # buckets[strength][h] -> Liste von Vorwärtsrenditen
    buckets: dict[str, dict[int, list[float]]] = defaultdict(
        lambda: defaultdict(list))
    all_returns: dict[int, list[float]] = defaultdict(list)
    n_dates = 0

    for j in cal.positions(min_history=args.min_history, horizon=max_h,
                           step=args.step):
        insts, meta = [], []
        for tk, candles in store.items():
            t = cal.index_at(tk, j)
            if t is None or t < args.min_history or not _liquid(candles, t):
                continue
            price = candles[t].c
            if price <= 0:
                continue
            # Gleiches Eingangsfenster wie die Produktion (YF_KEEP_CANDLES).
            hist = candles[max(0, t - SCORING_WINDOW + 1): t + 1]
            pm = meta_map.get(tk, {})
            insts.append(InstrumentData(
                instrument_id=tk, ticker=tk, asset_class="Aktie",
                sector=pm.get("sector"), industry=pm.get("industry"),
                market_cap=pm.get("market_cap"),
                technicals=technicals_from_candles(hist, price=price),
                fundamentals={}))
            fwd = {}
            for h in horizons:
                e = cal.index_at(tk, min(j + h, cal.n - 1))
                e = t if e is None else max(e, t)
                fwd[h] = max(-CAP, min(CAP, candles[e].c / price - 1.0))
            meta.append((tk, fwd))

        if len(insts) < 20:
            continue
        n_dates += 1
        ctx = ScoringContext(insts, min_peers=engine.min_peers)
        for inst, (tk, fwd) in zip(insts, meta):
            sc = engine.score_instrument(inst, ctx)
            bd = build_breakdown(sc, engine.composites, engine.computors)
            for h in horizons:
                buckets[bd.signal_strength][h].append(fwd[h])
                all_returns[h].append(fwd[h])

    print(f"{n_dates} Stichtage ausgewertet\n")
    for h in horizons:
        base = statistics.median(all_returns[h]) if all_returns[h] else 0.0
        print(f"HORIZONT {h} HANDELSTAGE")
        print(f"{'Stufe':<14}{'n':>8}{'Median':>10}{'Ø(gek.)':>10}"
              f"{'Treffer':>10}{'vs alle':>11}")
        print("-" * 63)
        for s in ORDER:
            v = buckets[s][h]
            if len(v) < 50:
                print(f"{s:<14}{len(v):>8}   zu wenig")
                continue
            med = statistics.median(v)
            print(f"{s:<14}{len(v):>8}{med:>9.2%}{statistics.mean(v):>10.2%}"
                  f"{sum(1 for x in v if x > 0)/len(v):>9.1%}"
                  f"{(med - base)*100:>10.2f}pp")
        print(f"{'alle Titel':<14}{len(all_returns[h]):>8}{base:>9.2%}"
              f"{statistics.mean(all_returns[h]):>10.2%}"
              f"{sum(1 for x in all_returns[h] if x > 0)/len(all_returns[h]):>9.1%}")
        # Monotonie ist der eigentliche Test: stark > moderat > schwach.
        meds = [(s, statistics.median(buckets[s][h]))
                for s in (SignalStrength.STRONG, SignalStrength.MODERATE,
                          SignalStrength.WEAK)
                if len(buckets[s][h]) >= 50]
        if len(meds) == 3:
            ok = meds[0][1] >= meds[1][1] >= meds[2][1]
            print(f"  Rangfolge stark >= moderat >= schwach: "
                  f"{'ERFUELLT' if ok else 'NICHT erfuellt'}")
        print()

    print("GRENZEN")
    print("  Survivorship Bias: Die Kerzen-Caches enthalten nur heute noch")
    print("  gelistete Titel; zwischenzeitlich delistete fehlen. Das verzerrt")
    print("  ALLE Stufen nach oben — der VERGLEICH zwischen den Stufen bleibt")
    print("  aussagekraeftig, die absoluten Renditen nicht.")
    print("  Keine Handelskosten, kein Slippage, keine Fundamentaldaten.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
