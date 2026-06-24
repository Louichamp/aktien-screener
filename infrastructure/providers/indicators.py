"""Technische Indikatoren aus OHLCV-Kerzen (dependency-frei, reines Python).

Bewusst ohne pandas/numpy: Der Provider beschafft täglich Hunderte Symbole;
ein schlanker, allokationsarmer Pfad hält den Ingest schnell und die
Abhängigkeiten klein. Alle Funktionen sind robust gegen kurze Reihen
(geben dann `None`).
"""
from __future__ import annotations

from screener.zones import Candle


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

    Rückgabe ist auf das Niveau normiert (~ %/Bar), sodass nur das Vorzeichen
    und die Größenordnung zählen — passend für die Trend-Klassifikation.
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


def technicals_from_candles(candles: list[Candle], *, price: float) -> dict[str, float]:
    """Verdichtet eine Kerzenreihe (alt -> neu) zu dem `technicals`-Dict,
    das ScoreEngine, Zonen-/Level- und Status-Engine erwarten."""
    closes = [c.c for c in candles]
    vols = [c.v for c in candles]
    ema50 = ema_series(closes, 50)
    ema200 = ema_series(closes, 200)
    avg_vol = sma(vols, 20)
    t: dict[str, float] = {"close": price}
    a = atr(candles)
    if a is not None:
        t["atr"] = a
    if len(ema50) >= 50:
        t["ema_50"] = ema50[-1]
        s = slope(ema50, 10)
        if s is not None:
            t["ema_50_slope"] = s
    if len(ema200) >= 200:
        t["ema_200"] = ema200[-1]
        s = slope(ema200, 20)
        if s is not None:
            t["ema_200_slope"] = s
    sma200 = sma(closes, 200)
    if sma200 is not None:
        t["sma_200"] = sma200
    r = rsi(closes)
    if r is not None:
        t["rsi"] = r
    if avg_vol and avg_vol > 0 and vols:
        t["volume_ratio"] = vols[-1] / avg_vol
    if len(closes) > 21:
        t["roc"] = (closes[-1] / closes[-21] - 1.0) * 100.0
    return t
