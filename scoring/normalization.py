"""Zustandslose Normalisierungs-Helfer für absolute Banding-Scores.

Cross-sectional/sektor-neutrale Normalisierung lebt bewusst NICHT hier,
sondern im `ScoringContext`, weil sie die Universumsverteilung braucht.
"""
from __future__ import annotations


def clamp(x: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, x))


def band(value: float | None, breakpoints: list[tuple[float, float]]) -> float | None:
    """Stückweise lineare Abbildung Kennzahl -> Score.

    `breakpoints`: (x, score)-Stützpunkte. Außerhalb wird auf den Rand geklemmt.
    Beispiel RSI-Sweetspot: band(rsi, [(30, 4), (55, 8), (70, 9), (80, 5), (90, 2)]).
    """
    if value is None or not breakpoints:
        return None
    pts = sorted(breakpoints)
    if value <= pts[0][0]:
        return pts[0][1]
    if value >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= value <= x1:
            t = 0.0 if x1 == x0 else (value - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return pts[-1][1]
