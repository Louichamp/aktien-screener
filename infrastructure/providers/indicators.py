"""Technische Indikatoren aus OHLCV-Kerzen (dependency-frei, reines Python).

Bewusst ohne pandas/numpy: Der Provider beschafft täglich Tausende Symbole;
ein schlanker, allokationsarmer Pfad hält den Ingest schnell und die
Abhängigkeiten klein. Alle Funktionen sind robust gegen kurze Reihen
(geben dann `None`).
"""
from __future__ import annotations

import math

from screener.zones import Candle


# ── Basishelfer ───────────────────────────────────────────────────────────────

def sma(values: list[float], period: int) -> float | None:
    if len(values) < period or period <= 0:
        return None
    return sum(values[-period:]) / period


def ema_series(values: list[float], period: int) -> list[float]:
    """Vollständige EMA-Reihe (gleiche Länge wie `values`)."""
    if not values or period <= 0:
        return []
    k = 2.0 / (period + 1.0)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1.0 - k))
    return out


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return ema_series(values, period)[-1]


def rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder-RSI."""
    if len(closes) <= period:
        return None
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(d, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0.0)) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def atr(candles: list[Candle], period: int = 14) -> float | None:
    """Wilder-ATR aus True Range."""
    if len(candles) <= period:
        return None
    trs: list[float] = []
    for i in range(1, len(candles)):
        c0, c1 = candles[i - 1], candles[i]
        trs.append(max(c1.h - c1.l, abs(c1.h - c0.c), abs(c1.l - c0.c)))
    a = sum(trs[:period]) / period
    for tr in trs[period:]:
        a = (a * (period - 1) + tr) / period
    return a


def slope(values: list[float], lookback: int = 10) -> float | None:
    """Normierte Steigung (Least-Squares) der letzten `lookback` Werte.

    Rückgabe ist auf das Niveau normiert (~%/Bar), sodass nur Vorzeichen
    und Größenordnung zählen — passend für die Trend-Klassifikation.
    """
    if len(values) < lookback or lookback < 2:
        return None
    ys = values[-lookback:]
    n = len(ys)
    xs = list(range(n))
    mx = (n - 1) / 2.0
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    b = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / denom
    return b / my if my else None


# ── Neue Indikatoren ──────────────────────────────────────────────────────────

def macd(closes: list[float],
         fast: int = 12, slow: int = 26, signal: int = 9
         ) -> dict[str, float] | None:
    """MACD-Linie, Signal-Linie und Histogramm (in Preis-Einheiten)."""
    if len(closes) < slow + signal:
        return None
    fast_s = ema_series(closes, fast)
    slow_s = ema_series(closes, slow)
    macd_line = [f - s for f, s in zip(fast_s, slow_s)]
    if len(macd_line) < signal:
        return None
    sig_line = ema_series(macd_line, signal)
    m_val = macd_line[-1]
    s_val = sig_line[-1]
    return {"macd": m_val, "macd_signal": s_val, "macd_hist": m_val - s_val}


def bollinger_bands(closes: list[float],
                    period: int = 20, mult: float = 2.0
                    ) -> dict[str, float] | None:
    """Bollinger Bänder: Mitte, oben, unten, %B (0=unten, 1=oben), Breite."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    mean = sum(window) / period
    var = sum((x - mean) ** 2 for x in window) / period
    std = math.sqrt(max(var, 0.0))
    upper = mean + mult * std
    lower = mean - mult * std
    close = closes[-1]
    pct_b = (close - lower) / (upper - lower) if upper != lower else 0.5
    width = (upper - lower) / mean if mean else 0.0
    return {
        "bb_upper": upper, "bb_lower": lower, "bb_mid": mean,
        "bb_pct": pct_b, "bb_width": width,
    }


def stochastic(candles: list[Candle],
               period: int = 14, smooth: int = 3
               ) -> dict[str, float] | None:
    """Stochastik %K (roh) und %D (geglättet), 0..100."""
    if len(candles) < period + smooth - 1:
        return None
    ks: list[float] = []
    for i in range(period - 1, len(candles)):
        seg = candles[i - period + 1: i + 1]
        lo = min(c.l for c in seg)
        hi = max(c.h for c in seg)
        ks.append((candles[i].c - lo) / (hi - lo) * 100.0 if hi != lo else 50.0)
    if len(ks) < smooth:
        return None
    d = sum(ks[-smooth:]) / smooth
    return {"stoch_k": ks[-1], "stoch_d": d}


def _wilder_smooth(vals: list[float], period: int) -> list[float]:
    """Wilder-Glättung: Initial-SMA, dann fortlaufend wie bei ATR."""
    if len(vals) < period:
        return []
    out = [sum(vals[:period]) / period]
    for v in vals[period:]:
        out.append((out[-1] * (period - 1) + v) / period)
    return out


def adx(candles: list[Candle], period: int = 14) -> dict[str, float] | None:
    """ADX, DI+ und DI− (Wilder, 14 Perioden). Benötigt mind. 2×period+1 Kerzen."""
    if len(candles) < period * 2 + 1:
        return None
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    trs: list[float] = []
    for i in range(1, len(candles)):
        prev, cur = candles[i - 1], candles[i]
        up = cur.h - prev.h
        dn = prev.l - cur.l
        plus_dm.append(up if up > dn and up > 0 else 0.0)
        minus_dm.append(dn if dn > up and dn > 0 else 0.0)
        trs.append(max(cur.h - cur.l, abs(cur.h - prev.c), abs(cur.l - prev.c)))

    s_tr = _wilder_smooth(trs, period)
    s_pdm = _wilder_smooth(plus_dm, period)
    s_mdm = _wilder_smooth(minus_dm, period)
    if not s_tr:
        return None

    di_plus = [100.0 * p / t if t > 0 else 0.0 for p, t in zip(s_pdm, s_tr)]
    di_minus = [100.0 * m / t if t > 0 else 0.0 for m, t in zip(s_mdm, s_tr)]
    dxs = [
        100.0 * abs(p - m) / (p + m) if (p + m) > 0 else 0.0
        for p, m in zip(di_plus, di_minus)
    ]
    adx_vals = _wilder_smooth(dxs, period)
    if not adx_vals:
        return None
    return {
        "adx": adx_vals[-1],
        "dmi_plus": di_plus[-1],
        "dmi_minus": di_minus[-1],
    }


def choppiness_index(candles: list[Candle], period: int = 14) -> float | None:
    """Choppiness Index: ~100 = Seitwärts, ~25 = stark trendend."""
    if len(candles) < period + 1:
        return None
    seg = candles[-(period + 1):]
    hi = max(c.h for c in seg)
    lo = min(c.l for c in seg)
    rng = hi - lo
    if rng <= 0:
        return None
    total_tr = 0.0
    for i in range(1, len(seg)):
        prev, cur = seg[i - 1], seg[i]
        total_tr += max(cur.h - cur.l, abs(cur.h - prev.c), abs(cur.l - prev.c))
    if total_tr <= 0:
        return None
    return 100.0 * math.log10(total_tr / rng) / math.log10(period)


def obv_series(candles: list[Candle]) -> list[float]:
    """On-Balance Volume (akkumuliert)."""
    if not candles:
        return []
    out = [0.0]
    for i in range(1, len(candles)):
        prev, cur = candles[i - 1], candles[i]
        if cur.c > prev.c:
            out.append(out[-1] + cur.v)
        elif cur.c < prev.c:
            out.append(out[-1] - cur.v)
        else:
            out.append(out[-1])
    return out


def structure_counts(candles: list[Candle], lookback: int = 20) -> dict[str, int]:
    """Zählt HH, HL, LH, LL in den letzten `lookback` Kerzen."""
    seg = candles[-lookback:] if len(candles) >= lookback else candles
    hh = hl = lh = ll = 0
    for i in range(1, len(seg)):
        prev, cur = seg[i - 1], seg[i]
        if cur.h > prev.h:
            hh += 1
        else:
            lh += 1
        if cur.l > prev.l:
            hl += 1
        else:
            ll += 1
    return {"hh": hh, "hl": hl, "lh": lh, "ll": ll}


# ── Statistische Robustheits-Helfer ───────────────────────────────────────────

def log_returns(closes: list[float]) -> list[float]:
    """Tägliche Log-Renditen r_t = ln(P_t / P_{t-1}); überspringt nicht-positive Kurse."""
    out: list[float] = []
    for i in range(1, len(closes)):
        p0, p1 = closes[i - 1], closes[i]
        if p0 > 0 and p1 > 0:
            out.append(math.log(p1 / p0))
    return out


def winsorize(values: list[float], cap: float = 0.25) -> list[float]:
    """Begrenzt Ausreißer auf ±cap (Default ±25 % Tagesrendite).

    Einzelne fehlerhafte Ticks/nicht-adjustierte Splits verzerren Varianz- und
    Drift-Schätzer massiv. Winsorizing (statt Entfernen) erhält die Stichprobengröße
    und macht σ/μ robust, ohne echte (gedeckelte) Bewegungen ganz zu verwerfen.
    """
    return [max(-cap, min(cap, v)) for v in values]


def efficiency_ratio(closes: list[float], period: int = 20) -> float | None:
    """Kaufman Efficiency Ratio (0..1): Netto-Bewegung / Summe der Absolutschritte.

    1.0 = perfekt gerichteter (sauberer) Trend, ~0 = reines Zickzack. Misst die
    QUALITÄT einer Bewegung unabhängig von ihrer Richtung — ein robustes,
    O(period)-Maß zur Unterscheidung tragfähiger Trends von Rauschen.
    """
    if len(closes) < period + 1:
        return None
    seg = closes[-(period + 1):]
    net = abs(seg[-1] - seg[0])
    path = sum(abs(seg[i] - seg[i - 1]) for i in range(1, len(seg)))
    if path <= 0:
        return None
    return net / path


def trend_r2(closes: list[float], period: int = 63) -> float | None:
    """Bestimmtheitsmaß R² einer linearen Regression von ln(Kurs) gegen die Zeit.

    Misst die Persistenz/Geradlinigkeit des Trends: R²≈1 = stetiger Auf-/Abtrend,
    R²≈0 = richtungsloses Rauschen. Auf Log-Kurse angewendet, weil ein Trend in
    der Rendite-Welt exponentiell ist. Robust und in O(period) berechenbar.
    """
    if len(closes) < period:
        return None
    seg = closes[-period:]
    ys = [math.log(p) for p in seg if p > 0]
    if len(ys) < period:
        return None
    n = len(ys)
    xs = list(range(n))
    mx = (n - 1) / 2.0
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    return (sxy * sxy) / (sxx * syy)          # = Pearson r²


def max_drawdown(closes: list[float], period: int = 126) -> float | None:
    """Maximaler Peak-to-Trough-Verlust (0..1) im Fenster — Tail-Risiko-Maß.

    Erfasst das tatsächlich erlittene Abwärtsrisiko deutlich besser als die
    symmetrische ATR/Vola, weil es Pfadabhängigkeit (Crash-Tiefe) abbildet.
    """
    if len(closes) < 2:
        return None
    seg = closes[-period:] if len(closes) >= period else closes
    peak = seg[0]
    mdd = 0.0
    for p in seg:
        if p > peak:
            peak = p
        if peak > 0:
            mdd = max(mdd, (peak - p) / peak)
    return mdd


def downside_deviation(rets: list[float], mar: float = 0.0,
                       periods_per_year: int = 252) -> float | None:
    """Annualisierte Downside-Deviation (Sortino-Nenner): nur negative Abweichungen.

    σ_d = sqrt( mean( min(r - MAR, 0)² ) ) · sqrt(252). Bestraft — anders als die
    symmetrische Standardabweichung — ausschließlich Verlustvolatilität, was dem
    realen Risikoempfinden und institutioneller Risikomessung entspricht.
    """
    if len(rets) < 2:
        return None
    downs = [min(r - mar, 0.0) ** 2 for r in rets]
    daily = math.sqrt(sum(downs) / len(downs))
    return daily * math.sqrt(periods_per_year)


def realized_volatility(rets: list[float], periods_per_year: int = 252) -> float | None:
    """Annualisierte realisierte Volatilität aus (winsorisierten) Log-Renditen."""
    if len(rets) < 2:
        return None
    mu = sum(rets) / len(rets)
    var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(max(var, 0.0)) * math.sqrt(periods_per_year)


# ── Haupt-Funktion ────────────────────────────────────────────────────────────

def technicals_from_candles(candles: list[Candle], *, price: float) -> dict[str, float]:
    """Verdichtet eine Kerzenreihe (alt -> neu) zu dem `technicals`-Dict,
    das ScoreEngine, Zonen-/Level- und Status-Engine erwarten."""
    closes = [c.c for c in candles]
    vols = [c.v for c in candles]
    n = len(candles)
    t: dict[str, float] = {"close": price}

    # ── ATR ──────────────────────────────────────────────────────────────
    a = atr(candles)
    if a is not None:
        t["atr"] = a

    # ── EMAs (20, 50, 100, 200) + Steigungen ─────────────────────────────
    ema_cfgs = (
        (20,  "ema_20",  10),
        (50,  "ema_50",  10),
        (100, "ema_100", 20),
        (200, "ema_200", 20),
    )
    for period, key, slb in ema_cfgs:
        s = ema_series(closes, period)
        if len(s) >= period:
            t[key] = s[-1]
            sl = slope(s, slb)
            if sl is not None:
                t[f"{key}_slope"] = sl

    sma200_val = sma(closes, 200)
    if sma200_val is not None:
        t["sma_200"] = sma200_val

    # ── RSI ──────────────────────────────────────────────────────────────
    r = rsi(closes)
    if r is not None:
        t["rsi"] = r

    # ── MACD ─────────────────────────────────────────────────────────────
    macd_res = macd(closes)
    if macd_res is not None:
        t.update(macd_res)
        if price > 0:
            t["macd_hist_pct"] = macd_res["macd_hist"] / price * 100.0

    # ── Bollinger Bänder ──────────────────────────────────────────────────
    bb = bollinger_bands(closes)
    if bb is not None:
        t.update(bb)

    # ── Stochastik ────────────────────────────────────────────────────────
    stoch = stochastic(candles)
    if stoch is not None:
        t.update(stoch)

    # ── ADX / DMI ────────────────────────────────────────────────────────
    adx_res = adx(candles)
    if adx_res is not None:
        t.update(adx_res)

    # ── Choppiness Index ──────────────────────────────────────────────────
    chop = choppiness_index(candles)
    if chop is not None:
        t["chop"] = chop

    # ── Volumen ───────────────────────────────────────────────────────────
    avg_vol = sma(vols, 20)
    if avg_vol and avg_vol > 0 and vols:
        t["volume_ratio"] = vols[-1] / avg_vol

    # OBV — normierter Slope: Anteil des mittleren Tagesvolumens pro Bar
    # Wert nahe +1 = alles Aufwärtsvolumen, nahe -1 = alles Abwärtsvolumen.
    obv = obv_series(candles)
    if len(obv) >= 21 and avg_vol and avg_vol > 0:
        lookback = min(20, len(obv) - 1)
        obv_change = obv[-1] - obv[-(lookback + 1)]
        t["obv_slope"] = obv_change / (avg_vol * lookback)

    # Aufwärts-Volumen-Anteil (letzte 20 Kerzen)
    seg20 = candles[-20:] if n >= 20 else candles
    if len(seg20) >= 2:
        up_vol = sum(c.v for c in seg20 if c.c >= c.o)
        tot_vol = sum(c.v for c in seg20)
        if tot_vol > 0:
            t["up_vol_ratio"] = up_vol / tot_vol

    # Distributionstage (letzte 25 Kerzen):
    # Kursrückgang > 0.2 % gegenüber Vortag bei überdurchschnittlichem Volumen.
    if avg_vol and avg_vol > 0 and n >= 2:
        seg25 = candles[-(min(25, n)):]
        dist = 0
        for i in range(1, len(seg25)):
            c, pc = seg25[i], seg25[i - 1]
            if (c.c < pc.c and c.v > avg_vol
                    and pc.c > 0 and (pc.c - c.c) / pc.c > 0.002):
                dist += 1
        t["distribution_days"] = float(dist)

    # ── Rate of Change (mehrere Perioden) ─────────────────────────────────
    for bars, key in ((21, "ret_1m"), (63, "ret_3m"), (126, "ret_6m"), (252, "ret_1y")):
        if n > bars and closes[-(bars + 1)] > 0:
            t[key] = (closes[-1] / closes[-(bars + 1)] - 1.0) * 100.0
    if "ret_1m" in t:
        t["roc"] = t["ret_1m"]          # Rückwärtskompatibles Alias

    # ── Chartstruktur (HH / HL / LH / LL der letzten 20 Kerzen) ─────────
    struct = structure_counts(candles, 20)
    t["hh_count"] = float(struct["hh"])
    t["hl_count"] = float(struct["hl"])
    t["lh_count"] = float(struct["lh"])
    t["ll_count"] = float(struct["ll"])

    # ── Trend-Qualität: Efficiency Ratio + Regressions-R² ───────────────
    er = efficiency_ratio(closes, 20)
    if er is not None:
        t["efficiency_ratio"] = er
    r2 = trend_r2(closes, 63)
    if r2 is not None:
        t["trend_r2"] = r2

    # ── Risiko-Statistik: robuste (winsorisierte) Renditemomente ─────────
    # Preis-Level-Indikatoren (EMA/ATR/BB) laufen auf Rohkursen; die
    # statistischen Momente nutzen winsorisierte Log-Renditen, damit ein
    # einzelner Fehl-Tick Vola/Drawdown/Forecast nicht verzerrt.
    rets = log_returns(closes)
    if len(rets) >= 20:
        wr = winsorize(rets[-252:])           # bis zu 1 Jahr, ausreißerrobust
        dd = downside_deviation(wr)
        if dd is not None:
            t["downside_dev"] = dd
        rv = realized_volatility(wr)
        if rv is not None:
            t["realized_vol"] = rv
    mdd = max_drawdown(closes, 126)
    if mdd is not None:
        t["max_drawdown"] = mdd

    return t
