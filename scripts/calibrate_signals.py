"""Offline-Signalkalibrierung: empirische Vorhersagegüte (IC) aus Kurshistorie.

Dies ist das selbst-validierende Herz des Systems. Es beantwortet pro Signal die
Frage „hat diese Information in der Vergangenheit zukünftige Renditen erklärt —
stabil über Marktphasen?" und leitet daraus REGULARISIERTE, evidenzbasierte
Gewichte ab. Methodik (institutioneller Standard, Point-in-Time):

  1. Für ein Sample des Universums die VOLLE Kerzenhistorie holen (Yahoo, gratis).
  2. An monatlichen Rebalancing-Terminen t (nur Daten ≤ t verwenden — kein
     Look-Ahead) den Querschnitt scoren und die realisierte Vorwärtsrendite
     (t → t+h) je Horizont h bestimmen.
  3. Je Termin und Signal die Querschnitts-Rang-Korrelation (IC) berechnen und das
     Regime des Termins taggen.
  4. Über alle Termine zu IC_mean / IC_stability / IC_by_regime / Halbwertszeit
     aggregieren und via Shrinkage gegen den Prior zu Gewichten verdichten.

Ergebnis → `data/signal_ic.json` (nicht versioniert). Die ScoreEngine kann diese
Gewichte optional laden; ohne Datei bleibt das heutige Verhalten exakt erhalten.

WICHTIG — Geltungsbereich: Sauber Point-in-Time validierbar sind die TECHNISCHEN
Signale (aus Kerzen rekonstruierbar). Fundamentale Signale (fund_quality, growth,
valuation) bräuchten Point-in-Time-Fundamentaldaten, die hier nicht vorliegen; sie
werden NICHT empirisch gewichtet (Prior bleibt). Das ist eine bewusste, dokumentierte
Grenze statt einer Look-Ahead-verzerrten Scheingenauigkeit.

  python scripts/calibrate_signals.py --sample 200 --step 21 --horizons 21,63,126
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scoring import InstrumentData, ScoreEngine, ScoringContext
from scoring.composites import DEFAULT_COMPOSITES
from scoring.validation import build_panel_calendar, classify_regime, redundancy_report
from scoring.validation.ic import ic_summary, rank_ic, regularized_weights, signal_half_life
from infrastructure.providers.indicators import technicals_from_candles

# Nur diese Signale sind aus Kerzen Point-in-Time rekonstruierbar.
TECHNICAL_SLUGS = ["trend", "rel_strength", "market_leadership", "momentum",
                   "volume", "institutional_demand", "breakout", "setup"]

# Eingangsfenster der Indikatorberechnung — MUSS der Produktion entsprechen.
# Produktion: YF_PERIOD=1y + YF_KEEP_CANDLES=260 (siehe compute-scores.yml und
# YahooMarketDataProvider). Vorher lief die Kalibrierung auf `candles[:t+1]`,
# also auf einem mit jedem Termin wachsenden Fenster von bis zu ~3000 Bars —
# gleiche Funktionen, andere Eingangsdaten. Betroffen sind alle Kennzahlen,
# deren Wert vom Fenster abhängt (EMA200-Einschwingen, ret_1y, Fibonacci-/
# Volumenprofil-Spannweiten).
SCORING_WINDOW = int(os.getenv("YF_KEEP_CANDLES", "260"))


def run_ic_backtest(candle_data: dict[str, dict],
                    *, horizons: list[int], step: int = 21,
                    min_history: int = 252,
                    window: int | None = None) -> dict:
    """Point-in-Time-IC-Backtest auf vorab geholten Kerzen (rein, netzwerkfrei).

    `candle_data`: {ticker: {"candles": [Candle...], "sector": str, "industry": str}}.
    Gibt das vollständige Kalibrierungs-Resultat als serialisierbares Dict zurück.

    Die Stichtage liegen auf einer GEMEINSAMEN Handelstagsachse (siehe
    `scoring.validation.panel`): Der Querschnitt vergleicht damit tatsächlich
    denselben Kalendertag. Vorher wurde über den Listenindex ausgerichtet, was
    bei unterschiedlich langen Historien verschiedene Zeitpunkte vermischte.
    """
    engine = ScoreEngine()
    max_h = max(horizons)
    window = window or SCORING_WINDOW

    series = {tk: d["candles"] for tk, d in candle_data.items()}
    cal = build_panel_calendar(series)
    if not cal.dated:
        print("  WARNUNG: Kerzen ohne Datum — Ausrichtung vom Reihenende. "
              "Korrekt nur, solange alle Reihen am selben Tag enden.",
              file=sys.stderr)

    # ic_series[slug][h] -> Liste von Termin-ICs; regimes -> Liste von Labels (je Termin).
    ic_series: dict[str, dict[int, list[float | None]]] = {
        s: {h: [] for h in horizons} for s in TECHNICAL_SLUGS}
    regimes: list[str] = []
    last_panel_scores: list[dict[str, float]] = []
    n_dates = 0

    for j in cal.positions(min_history=min_history, horizon=max_h, step=step):
        # Querschnitts-Panel am Stichtag j aufbauen (nur Daten ≤ Stichtag).
        insts: list[InstrumentData] = []
        meta: list[tuple[str, dict, dict[int, float]]] = []   # (id, regime_row, fwd_by_h)
        for tk, d in candle_data.items():
            candles = d["candles"]
            idx = cal.index_at(tk, j)
            if idx is None or idx < min_history:
                continue
            price = candles[idx].c
            if not price or price <= 0:
                continue

            # Vorwärtsrendite ebenfalls über die gemeinsame Achse: h Stichtage
            # weiter, nicht h Positionen in der eigenen (evtl. lückenhaften) Reihe.
            fwd: dict[int, float | None] = {}
            for h in horizons:
                f_idx = cal.index_at(tk, j + h) if (j + h) < cal.n else None
                fwd[h] = ((candles[f_idx].c / price - 1.0)
                          if (f_idx is not None and f_idx > idx
                              and candles[f_idx].c > 0) else None)
            if all(v is None for v in fwd.values()):
                continue

            hist = candles[max(0, idx - window + 1): idx + 1]
            tech = technicals_from_candles(hist, price=price)
            inst = InstrumentData(
                instrument_id=tk, ticker=tk, asset_class="Aktie",
                sector=d.get("sector"), industry=d.get("industry"),
                market_cap=d.get("market_cap"), technicals=tech, fundamentals={})
            insts.append(inst)
            regime_row = {
                "realized_vol": tech.get("realized_vol"),
                "efficiency_ratio": tech.get("efficiency_ratio"),
                "above_ema200": 1.0 if (tech.get("ema_200") and price > tech["ema_200"]) else 0.0,
                "ret_1m": tech.get("ret_1m"),
            }
            meta.append((tk, regime_row, fwd))

        if len(insts) < 5:                        # zu dünner Querschnitt für IC
            continue

        ctx = ScoringContext(insts, min_peers=engine.min_peers)
        scored = {i.instrument_id: engine.score_instrument(i, ctx) for i in insts}
        regime = classify_regime([m[1] for m in meta])
        regimes.append(regime.label)
        n_dates += 1

        panel_scores: list[dict[str, float]] = []
        for slug in TECHNICAL_SLUGS:
            for h in horizons:
                sig_vals, fwd_vals = [], []
                for tk, _row, fwd in meta:
                    res = scored[tk].results.get(slug)
                    if res is None or not res.ok or res.raw.get("missing"):
                        continue
                    if fwd[h] is None:
                        continue
                    sig_vals.append(res.score)
                    fwd_vals.append(fwd[h])
                ic_series[slug][h].append(rank_ic(sig_vals, fwd_vals))

        # Letztes Panel für die Redundanz-Diagnose festhalten.
        for tk, _row, _fwd in meta:
            row = {}
            for slug in TECHNICAL_SLUGS:
                res = scored[tk].results.get(slug)
                if res is not None and res.ok and not res.raw.get("missing"):
                    row[slug] = res.score
            if row:
                panel_scores.append(row)
        last_panel_scores = panel_scores

    # ── Aggregation ──────────────────────────────────────────────────────────
    primary_h = horizons[len(horizons) // 2]      # mittlerer Horizont als Leitgröße
    per_signal: dict[str, dict] = {}
    primary_stats = {}
    for slug in TECHNICAL_SLUGS:
        ic_by_h: dict[int, float] = {}
        horizon_detail = {}
        for h in horizons:
            st = ic_summary(slug, ic_series[slug][h], regimes)
            if st is not None:
                ic_by_h[h] = st.ic_mean
                horizon_detail[str(h)] = {
                    "ic_mean": round(st.ic_mean, 4), "ic_t_stat": round(st.ic_t_stat, 2),
                    "hit_rate": round(st.hit_rate, 3), "n": st.n_periods,
                    "reliable": st.reliable,
                    "by_regime": {k: round(v, 4) for k, v in st.by_regime.items()},
                }
        st_primary = ic_summary(slug, ic_series[slug][primary_h], regimes)
        if st_primary is not None:
            primary_stats[slug] = st_primary
        per_signal[slug] = {
            "horizons": horizon_detail,
            "half_life_bars": (round(hl, 1) if (hl := signal_half_life(ic_by_h)) else None),
        }

    tech_prior = DEFAULT_COMPOSITES["technical_rating"]
    rec_tech = regularized_weights(tech_prior, primary_stats)
    redundancy = (redundancy_report(last_panel_scores, TECHNICAL_SLUGS)
                  if last_panel_scores else {})

    n_with_peers = sum(1 for d in candle_data.values()
                       if d.get("sector") or d.get("industry"))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "point_in_time_cross_sectional_rank_ic",
        # Messbedingungen mitschreiben: ohne sie ist ein IC-Wert nicht einordenbar.
        "alignment": "trading_date" if cal.dated else "series_end_fallback",
        "scoring_window_bars": window,
        "peer_context": {
            "tickers_with_sector_or_industry": n_with_peers,
            "tickers_total": len(candle_data),
            "note": ("Ohne Branchen-/Sektorangabe fallen ALLE Peer-Perzentile auf "
                     "'universe' zurueck; rel_strength, market_leadership und "
                     "valuation messen dann etwas anderes als in Produktion."),
        },
        "primary_horizon": primary_h,
        "n_rebalance_dates": n_dates,
        "n_tickers": len(candle_data),
        "regime_distribution": {rg: regimes.count(rg) for rg in sorted(set(regimes))},
        "signals": per_signal,
        "recommended_weights": {
            "technical_rating": {k: round(v, 4) for k, v in rec_tech.items()},
            "_note": ("Nur technische Signale empirisch gewichtet; fundamentale "
                      "Signale behalten den Prior (keine Point-in-Time-Fundamentals)."),
        },
        "redundancy": redundancy,
    }


_EMPTY_META: dict[str, Any] = {"sector": None, "industry": None, "market_cap": None}


def _load_peer_meta(path: str | None) -> dict[str, dict]:
    """Branche/Sektor/Marktkapitalisierung je Ticker aus einem Snapshot-Cache.

    Ohne diese Angaben fallen SAEMTLICHE Peer-Perzentile auf `universe` zurueck
    (siehe ScoringContext.peers). `market_leadership` verliert dann drei seiner
    vier Faktoren und reduziert sich auf ret_3m — also auf die Hauptkomponente
    von `rel_strength`. Eine so gemessene Korrelation zwischen beiden ist ein
    Artefakt der Messbedingungen, keine Eigenschaft des Systems.
    """
    if not path:
        return {}
    import pickle
    try:
        with open(path, "rb") as fh:
            snaps = pickle.load(fh)
    except (OSError, ValueError, pickle.UnpicklingError) as exc:
        print(f"  Peer-Kontext nicht lesbar ({exc}) — ohne Branchenangaben.",
              file=sys.stderr)
        return {}
    out: dict[str, dict] = {}
    for tk, s in snaps.items():
        out[tk] = {"sector": getattr(s, "sector", None),
                   "industry": getattr(s, "industry", None),
                   "market_cap": getattr(s, "market_cap", None)}
    return out


async def _fetch_candles(tickers: list[str], *, period: str, concurrency: int) -> dict[str, dict]:
    from infrastructure.providers import YahooMarketDataProvider
    prov = YahooMarketDataProvider(period=period, max_concurrency=concurrency,
                                   with_fundamentals=True, keep_candles=10_000)
    out: dict[str, dict] = {}

    async def one(tk: str) -> None:
        snap = await prov.fetch(tk)
        if snap and len(snap.candles) >= 300:
            out[tk] = {"candles": snap.candles, "sector": snap.sector,
                       "industry": snap.industry, "market_cap": snap.market_cap}

    await asyncio.gather(*(one(tk) for tk in tickers))
    if hasattr(prov, "aclose"):
        await prov.aclose()
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=200, help="Anzahl Ticker (Stichprobe)")
    ap.add_argument("--step", type=int, default=21, help="Bar-Abstand der Rebalancing-Termine")
    ap.add_argument("--horizons", default="21,63,126", help="Vorwärtsrendite-Horizonte in Bars")
    ap.add_argument("--period", default="2y", help="Yahoo-Historie")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--from-cache", default=None,
                    help="Pickle mit {ticker: [Candle]} statt Yahoo-Abruf "
                         "(z.B. .cache/backtest_candles_12y.pkl) — netzfrei "
                         "und reproduzierbar")
    ap.add_argument("--meta-from", default=None,
                    help="Snapshot-Cache (z.B. .cache/full_snaps.pkl) fuer "
                         "echte Branche/Sektor/Marktkapitalisierung. OHNE das "
                         "fallen alle Peer-Perzentile auf 'universe' zurueck.")
    ap.add_argument("--window", type=int, default=None,
                    help=f"Eingangsfenster in Bars (Standard {SCORING_WINDOW} = Produktion)")
    ap.add_argument("--out", default=str(ROOT / "data" / "signal_ic.json"))
    args = ap.parse_args()

    horizons = [int(h) for h in args.horizons.split(",")]

    if args.from_cache:
        # Netzfreier Weg: dieselben Kerzen wie der Backtest, damit
        # Kalibrierung und Validierung auf derselben Grundlage laufen.
        import pickle
        with open(args.from_cache, "rb") as fh:
            store = pickle.load(fh)
        meta = _load_peer_meta(args.meta_from)
        candle_data = {tk: {"candles": c, **meta.get(tk, _EMPTY_META)}
                       for tk, c in list(store.items())[: args.sample]
                       if len(c) >= 300}
        have = sum(1 for d in candle_data.values() if d.get("industry") or d.get("sector"))
        print(f"  {len(candle_data)} Titel aus {args.from_cache}, "
              f"{have} davon mit echtem Branchen-/Sektor-Kontext", file=sys.stderr)
        if not have:
            print("  WARNUNG: ohne Peer-Kontext fallen alle Peer-Perzentile auf "
                  "'universe' zurueck — rel_strength/market_leadership/valuation "
                  "messen dann NICHT das Produktionsverhalten. Mit --meta-from "
                  "einen Snapshot-Cache angeben.", file=sys.stderr)
    else:
        from infrastructure.providers import build_universe
        universe = await build_universe(args.sample, source="broad")
        universe = universe[: args.sample]
        print(f"Hole Kerzen für {len(universe)} Titel (Period {args.period}) …",
              file=sys.stderr)
        candle_data = await _fetch_candles(universe, period=args.period,
                                           concurrency=args.concurrency)
        print(f"  {len(candle_data)} Titel mit ≥300 Bars verwendbar.", file=sys.stderr)
    if len(candle_data) < 20:
        print("FEHLER: zu wenig Historie für belastbare IC-Schätzung.", file=sys.stderr)
        raise SystemExit(1)

    result = run_ic_backtest(candle_data, horizons=horizons, step=args.step,
                             window=args.window)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Kalibrierung → {out_path}  ({result['n_rebalance_dates']} Termine, "
          f"eff. Signale {result.get('redundancy', {}).get('effective_signals', '?')})", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
