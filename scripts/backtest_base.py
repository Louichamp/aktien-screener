"""Walk-Forward-Backtest der Bodenbildungs-/Kaufzonen-Logik.

Beantwortet die Frage, die der Screener bisher NICHT beantworten konnte:
Wenn eine Basis als tragfähig gilt und der Kurs die Kaufzone (den Pivot)
durchbricht — geht es danach messbar häufiger nach oben als sonst?

Methodik (strikt point-in-time, kein Lookahead):
  * Für jeden Ticker wird die Historie Bar für Bar durchlaufen.
  * Zum Zeitpunkt t sieht `detect_base` AUSSCHLIESSLICH candles[:t].
  * Ein Ausbruchs-Ereignis ist: bei t-1 lag der Kurs auf/unter dem Pivot,
    bei t schließt er darüber. Einstieg = Schlusskurs von t.
  * Danach wird der Trade regelbasiert simuliert (Stopp aus der Basis,
    Ziele in R-Vielfachen) — inklusive der Frage, was ZUERST erreicht wurde.

Gegen eine Zufalls-Baseline mit identischer Stopp-Weite auf denselben
Tickern und Zeiträumen — sonst misst man nur den Aufwärtsdrift des Marktes.

    python scripts/backtest_base.py --tickers 400 --years 10 --horizon 60

Rohdaten landen in .cache/ (gitignored) und werden wiederverwendet.
"""
from __future__ import annotations

import argparse
import os
import pickle
import random
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, asdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from infrastructure.providers.indicators import atr as atr_fn, ema_series, slope
from screener.base_formation import BaseState, MAX_BASE_LEN, detect_base
from screener.zones import Candle

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache")
WINDOW = MAX_BASE_LEN + 60          # Sichtfenster für detect_base (+ Puffer für EMA200)


# --------------------------------------------------------------------------- #
#  Daten
# --------------------------------------------------------------------------- #
def load_candles(tickers: list[str], years: int) -> dict[str, list[Candle]]:
    """Lädt Tageskerzen (gecacht). Chunk-weise, damit Teilerfolge erhalten bleiben."""
    import warnings
    warnings.filterwarnings("ignore")
    import yfinance as yf

    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"backtest_candles_{years}y.pkl")
    store: dict[str, list[Candle]] = {}
    if os.path.exists(path):
        with open(path, "rb") as fh:
            store = pickle.load(fh)
        print(f"Cache: {len(store)} Ticker bereits vorhanden")

    todo = [t for t in tickers if t not in store]
    for i in range(0, len(todo), 40):
        chunk = todo[i:i + 40]
        try:
            df = yf.download(chunk, period=f"{years}y", interval="1d",
                             auto_adjust=True, progress=False,
                             group_by="ticker", threads=True)
        except Exception as exc:
            print(f"  Chunk {i // 40 + 1} fehlgeschlagen: {exc}")
            continue
        for t in chunk:
            try:
                sub = df[t].dropna() if len(chunk) > 1 else df.dropna()
            except Exception:
                continue
            if len(sub) < 400:
                continue
            store[t] = [Candle(float(r.Open), float(r.High), float(r.Low),
                               float(r.Close), float(r.Volume))
                        for r in sub.itertuples()]
        with open(path, "wb") as fh:
            pickle.dump(store, fh)
        print(f"  {min(i + 40, len(todo))}/{len(todo)} geladen "
              f"(gesamt {len(store)})", flush=True)
        time.sleep(1.0)
    return {t: c for t, c in store.items() if t in set(tickers)}


# --------------------------------------------------------------------------- #
#  Trade-Simulation
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class Trade:
    ticker: str
    idx: int
    quality: float
    state: str
    entry: float
    stop: float
    risk_pct: float
    ret_h: float                 # Rendite am Horizont-Ende
    mfe: float                   # größter Buchgewinn
    mae: float                   # größter Buchverlust
    r_multiple: float            # Ergebnis in R (Risiko-Einheiten)
    hit_2r_first: bool
    stopped_first: bool
    base_len: int = 0
    breakout_vol: float = 0.0


def _simulate(candles: list[Candle], t: int, entry: float, stop: float,
              horizon: int) -> tuple[float, float, float, float, bool, bool]:
    """Regelbasierter Trade-Verlauf ab Bar t (Einstieg zum Schluss von t).

    Wichtig für die Frage „ziemlich sicher nach oben": Es genügt nicht, die
    Rendite am Horizont zu messen — entscheidend ist, ob der Stopp ZUERST
    erreicht wurde. Ein Trade, der erst 20 % ins Minus läuft und dann
    zurückkommt, ist in der Praxis ein Verlust.
    """
    risk = entry - stop
    if risk <= 0:
        return 0.0, 0.0, 0.0, 0.0, False, False
    target_2r = entry + 2.0 * risk
    end = min(t + horizon, len(candles) - 1)
    mfe = mae = 0.0
    hit_2r = stopped = False
    for i in range(t + 1, end + 1):
        c = candles[i]
        mfe = max(mfe, c.h / entry - 1.0)
        mae = min(mae, c.l / entry - 1.0)
        if not hit_2r and not stopped:
            # Konservativ: Bei einer Kerze, die beides berührt, zählt der Stopp.
            if c.l <= stop:
                stopped = True
            elif c.h >= target_2r:
                hit_2r = True
    ret_h = candles[end].c / entry - 1.0
    if stopped:
        r_mult = -1.0
    elif hit_2r:
        r_mult = 2.0
    else:
        r_mult = (candles[end].c - entry) / risk
    return ret_h, mfe, mae, r_mult, hit_2r, stopped


def _liquid(candles: list[Candle], t: int, *, min_price: float,
            min_dollar_vol: float) -> bool:
    """Datenqualitäts-Gate. Ohne das sind die Auswertungen wertlos: In der
    Small-Cap-Stichprobe waren 58 % der Beobachtungen Penny-Werte oder
    illiquide, und die Mittelwerte entsprechend absurd (Ø +45 % bei Median 0 %).
    """
    if candles[t].c < min_price or t < 60:
        return False
    seg = candles[t - 60:t]
    return statistics.median(x.c * x.v for x in seg) >= min_dollar_vol


def _scan_ticker(args: tuple[str, list[Candle], int, int]) -> tuple[list[Trade], list[Trade]]:
    """Ein Ticker: alle Ausbruchs-Ereignisse + gleich viele Zufalls-Vergleiche."""
    ticker, candles, horizon, step = args
    n = len(candles)
    events: list[Trade] = []
    closes = [c.c for c in candles]
    ema200_full = ema_series(closes, 200)

    # `last_base` stammt immer aus dem VORIGEN Schleifendurchlauf, ist also zum
    # Zeitpunkt des Ausbruchs bereits bekannt gewesen — kein Lookahead.
    last_base = None

    start = max(260, WINDOW)
    for t in range(start, n - horizon, step):
        win = candles[max(0, t - WINDOW):t]
        if len(win) < 60:
            continue
        a = atr_fn(win)
        e200 = ema200_full[t - 1] if t - 1 < len(ema200_full) and t >= 200 else None
        sl = slope(ema200_full[:t], 20) if t >= 220 else None
        b = detect_base(win, price=candles[t - 1].c, atr=a, ema_200=e200, ema_200_slope=sl)
        if b is None:
            last_base = None
            continue

        # Ausbruch: Vorlauf-Bar unter/auf Pivot, aktueller Schluss darüber.
        prev_c = candles[t - 1].c
        cur = candles[t]
        if (last_base is not None and prev_c <= last_base.pivot
                and cur.c > last_base.pivot and last_base.stop_suggest
                and last_base.stop_suggest < cur.c):
            ret_h, mfe, mae, r_mult, hit2, stopped = _simulate(
                candles, t, cur.c, last_base.stop_suggest, horizon)
            base_vol = sum(x.v for x in win[-last_base.length:]) / max(last_base.length, 1)
            events.append(Trade(
                ticker=ticker, idx=t, quality=last_base.quality,
                state=last_base.state, entry=cur.c, stop=last_base.stop_suggest,
                risk_pct=(cur.c - last_base.stop_suggest) / cur.c,
                ret_h=ret_h, mfe=mfe, mae=mae, r_multiple=r_mult,
                hit_2r_first=hit2, stopped_first=stopped,
                base_len=last_base.length,
                breakout_vol=(cur.v / base_vol) if base_vol > 0 else 0.0))
        last_base = b

    # Baseline: gleiche Anzahl zufälliger Einstiege, gleiche Stopp-Weite in %.
    rng = random.Random(hash(ticker) & 0xFFFF)
    baseline: list[Trade] = []
    for ev in events:
        t = rng.randrange(start, n - horizon)
        entry = candles[t].c
        stop = entry * (1.0 - ev.risk_pct)
        ret_h, mfe, mae, r_mult, hit2, stopped = _simulate(candles, t, entry, stop, horizon)
        baseline.append(Trade(ticker, t, 0.0, "baseline", entry, stop, ev.risk_pct,
                              ret_h, mfe, mae, r_mult, hit2, stopped))
    return events, baseline


# --------------------------------------------------------------------------- #
#  Auswertung
# --------------------------------------------------------------------------- #
def _stats(trades: list[Trade], label: str) -> dict:
    if not trades:
        return {"label": label, "n": 0}
    rets = [t.ret_h for t in trades]
    return {
        "label": label,
        "n": len(trades),
        "hit_rate": sum(1 for r in rets if r > 0) / len(rets),
        "mean": statistics.mean(rets),
        "median": statistics.median(rets),
        "expectancy_r": statistics.mean(t.r_multiple for t in trades),
        "reached_2r": sum(1 for t in trades if t.hit_2r_first) / len(trades),
        "stopped": sum(1 for t in trades if t.stopped_first) / len(trades),
        "mean_mae": statistics.mean(t.mae for t in trades),
    }


def _print_table(rows: list[dict]) -> None:
    print(f"\n{'Bucket':<28}{'n':>7}{'Treffer':>9}{'Ø Rend':>9}{'Median':>9}"
          f"{'Erw. R':>9}{'+2R':>8}{'Stopp':>8}{'Ø MAE':>8}")
    print("-" * 95)
    for r in rows:
        if not r.get("n"):
            print(f"{r['label']:<28}{0:>7}   --")
            continue
        print(f"{r['label']:<28}{r['n']:>7}{r['hit_rate']:>8.1%}{r['mean']:>9.2%}"
              f"{r['median']:>9.2%}{r['expectancy_r']:>9.2f}{r['reached_2r']:>8.1%}"
              f"{r['stopped']:>8.1%}{r['mean_mae']:>8.2%}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", type=int, default=400)
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--horizon", type=int, default=60, help="Haltedauer in Bars")
    ap.add_argument("--step", type=int, default=2)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    args = ap.parse_args()

    import asyncio
    from infrastructure.providers.universe import build_universe
    uni = asyncio.run(build_universe(args.tickers, source="sp500"))
    tickers = [e["symbol"] for e in uni][:args.tickers]
    print(f"Universum: {len(tickers)} Ticker, {args.years} Jahre Historie")

    data = load_candles(tickers, args.years)
    print(f"Nutzbar: {len(data)} Ticker\n")
    if not data:
        print("Keine Daten — Abbruch.")
        return 1

    jobs = [(t, c, args.horizon, args.step) for t, c in data.items()]
    events: list[Trade] = []
    baseline: list[Trade] = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, (ev, bl) in enumerate(pool.map(_scan_ticker, jobs, chunksize=4), 1):
            events += ev
            baseline += bl
            if i % 50 == 0:
                print(f"  {i}/{len(jobs)} Ticker · {len(events)} Ereignisse "
                      f"· {time.time() - t0:.0f}s", flush=True)

    print(f"\n{len(events)} Ausbruchs-Ereignisse in {time.time() - t0:.0f}s")

    ready = [e for e in events if e.state == BaseState.READY]
    forming = [e for e in events if e.state == BaseState.FORMING]
    hq = [e for e in events if e.quality >= 7.5]
    hq_vol = [e for e in hq if e.breakout_vol >= 1.5]
    lq = [e for e in events if e.quality < 5.0]

    _print_table([
        _stats(baseline, "Zufalls-Baseline"),
        _stats(events, "ALLE Ausbrüche"),
        _stats(forming, "  aus 'in Bildung'"),
        _stats(ready, "  aus 'tragfähig'"),
        _stats(lq, "  Qualität < 5,0"),
        _stats(hq, "  Qualität >= 7,5"),
        _stats(hq_vol, "  Q>=7,5 + Volumen>=1,5x"),
    ])

    print("\nQualitäts-Dezile (Rendite am Horizont):")
    ev_sorted = sorted(events, key=lambda e: e.quality)
    k = max(len(ev_sorted) // 10, 1)
    for d in range(10):
        seg = ev_sorted[d * k:(d + 1) * k]
        if not seg:
            continue
        print(f"  D{d + 1}  Q {seg[0].quality:>4.1f}-{seg[-1].quality:>4.1f}  "
              f"n={len(seg):>4}  Ø {statistics.mean(s.ret_h for s in seg):>7.2%}  "
              f"Erw.R {statistics.mean(s.r_multiple for s in seg):>6.2f}  "
              f"Stopp {sum(1 for s in seg if s.stopped_first) / len(seg):>5.1%}")

    out = os.path.join(CACHE_DIR, "backtest_base_events.pkl")
    with open(out, "wb") as fh:
        pickle.dump({"events": [asdict(e) for e in events],
                     "baseline": [asdict(b) for b in baseline]}, fh)
    print(f"\nRohdaten: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
