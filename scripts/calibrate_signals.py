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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scoring import InstrumentData, ScoreEngine, ScoringContext
from scoring.composites import DEFAULT_COMPOSITES
from scoring.validation import classify_regime, redundancy_report
from scoring.validation.ic import ic_summary, rank_ic, regularized_weights, signal_half_life
from infrastructure.providers.indicators import technicals_from_candles

# Nur diese Signale sind aus Kerzen Point-in-Time rekonstruierbar.
TECHNICAL_SLUGS = ["trend", "rel_strength", "market_leadership", "momentum",
                   "volume", "institutional_demand", "breakout", "setup"]


def _forward_return(candles, t: int, h: int) -> float | None:
    if t + h >= len(candles):
        return None
    p0, p1 = candles[t].c, candles[t + h].c
    if p0 and p0 > 0 and p1 and p1 > 0:
        return p1 / p0 - 1.0
    return None


def run_ic_backtest(candle_data: dict[str, dict],
                    *, horizons: list[int], step: int = 21,
                    min_history: int = 252) -> dict:
    """Point-in-Time-IC-Backtest auf vorab geholten Kerzen (rein, netzwerkfrei).

    `candle_data`: {ticker: {"candles": [Candle...], "sector": str, "industry": str}}.
    Gibt das vollständige Kalibrierungs-Resultat als serialisierbares Dict zurück.
    """
    engine = ScoreEngine()
    max_h = max(horizons)
    # Globale Zeitachse über das längste verfügbare Sample.
    max_len = max((len(d["candles"]) for d in candle_data.values()), default=0)

    # ic_series[slug][h] -> Liste von Termin-ICs; regimes -> Liste von Labels (je Termin).
    ic_series: dict[str, dict[int, list[float | None]]] = {
        s: {h: [] for h in horizons} for s in TECHNICAL_SLUGS}
    regimes: list[str] = []
    last_panel_scores: list[dict[str, float]] = []
    n_dates = 0

    for t in range(min_history, max_len - max_h, step):
        # Querschnitts-Panel an Termin t aufbauen (nur Daten ≤ t).
        insts: list[InstrumentData] = []
        meta: list[tuple[str, dict, dict[int, float]]] = []   # (id, regime_row, fwd_by_h)
        for tk, d in candle_data.items():
            candles = d["candles"]
            if t >= len(candles):
                continue
            fwd = {h: _forward_return(candles, t, h) for h in horizons}
            if all(v is None for v in fwd.values()):
                continue
            tech = technicals_from_candles(candles[: t + 1], price=candles[t].c)
            inst = InstrumentData(
                instrument_id=tk, ticker=tk, asset_class="Aktie",
                sector=d.get("sector"), industry=d.get("industry"),
                market_cap=d.get("market_cap"), technicals=tech, fundamentals={})
            insts.append(inst)
            regime_row = {
                "realized_vol": tech.get("realized_vol"),
                "efficiency_ratio": tech.get("efficiency_ratio"),
                "above_ema200": 1.0 if (tech.get("ema_200") and candles[t].c > tech["ema_200"]) else 0.0,
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

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "point_in_time_cross_sectional_rank_ic",
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
    ap.add_argument("--out", default=str(ROOT / "data" / "signal_ic.json"))
    args = ap.parse_args()

    from infrastructure.providers import build_universe
    universe = await build_universe(source="broad")
    universe = universe[: args.sample]
    horizons = [int(h) for h in args.horizons.split(",")]

    print(f"Hole Kerzen für {len(universe)} Titel (Period {args.period}) …", file=sys.stderr)
    candle_data = await _fetch_candles(universe, period=args.period, concurrency=args.concurrency)
    print(f"  {len(candle_data)} Titel mit ≥300 Bars verwendbar.", file=sys.stderr)
    if len(candle_data) < 20:
        print("FEHLER: zu wenig Historie für belastbare IC-Schätzung.", file=sys.stderr)
        raise SystemExit(1)

    result = run_ic_backtest(candle_data, horizons=horizons, step=args.step)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Kalibrierung → {out_path}  ({result['n_rebalance_dates']} Termine, "
          f"eff. Signale {result.get('redundancy', {}).get('effective_signals', '?')})", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
