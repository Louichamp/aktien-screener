"""Markt-Regime aus dem Querschnitt (nicht simple Bull/Bear).

Ein Signal trägt in verschiedenen Marktphasen unterschiedlich viel Information:
Momentum funktioniert im trendkohärenten Markt und bricht im Mean-Reversion-/
Krisen-Regime. Damit IC regime-bedingt auswertbar wird, klassifiziert dieses
Modul jeden Rebalancing-Termin (bzw. den aktuellen Lauf) entlang dreier
orthogonaler, ökonomisch interpretierbarer Achsen:

  • Volatilitäts-Regime    — Median der annualisierten realisierten Vola
                             (low / mid / stress).
  • Trend-Kohärenz-Regime  — Marktbreite: Anteil der Titel in sauberem Auftrend
                             (efficiency_ratio hoch & Kurs > EMA200).
  • Dispersions-Regime     — Querschnitts-Streuung der Renditen (hoch = Dispersion/
                             stock-picking-freundlich, niedrig = korreliert/Makro).

Die Klassifikation nutzt ausschließlich bereits berechnete Felder und ist O(n).
Sie ist als QUERSCHNITTS-Statistik nur über die volle Kohorte stabil; auf
Teil-Slices ist sie als grober Proxy zu verstehen (dokumentierte Limitation).
"""
from __future__ import annotations

from dataclasses import dataclass


def _median(xs: list[float]) -> float | None:
    vals = sorted(v for v in xs if v is not None)
    if not vals:
        return None
    m = len(vals) // 2
    return vals[m] if len(vals) % 2 else (vals[m - 1] + vals[m]) / 2.0


@dataclass(slots=True)
class RegimeSnapshot:
    """Diskrete Regime-Labels + die zugrunde liegenden Roh-Statistiken."""
    vol: str                 # "low" | "mid" | "stress"
    trend: str               # "coherent" | "mixed" | "incoherent"
    dispersion: str          # "high" | "mid" | "low"
    median_vol: float | None
    trend_breadth: float | None
    return_dispersion: float | None
    n: int

    @property
    def label(self) -> str:
        """Kompaktes, in der IC-Auswertung als Bucket genutztes Gesamt-Label."""
        return f"{self.vol}|{self.trend}"


def classify_regime(panel: list[dict[str, float | None]],
                    *, vol_key: str = "realized_vol",
                    er_key: str = "efficiency_ratio",
                    above_200_key: str = "above_ema200",
                    ret_key: str = "ret_1m") -> RegimeSnapshot:
    """Klassifiziert ein Querschnitts-Panel in ein Regime.

    `panel` ist eine Liste von Dicts mit (mindestens optional) den Schlüsseln
    vol_key, er_key, above_200_key (1/0), ret_key. Fehlende Felder werden robust
    übersprungen. Schwellen sind an typischen Aktien-Niveaus kalibriert.
    """
    n = len(panel)
    vols = [row.get(vol_key) for row in panel]
    med_vol = _median([v for v in vols if v is not None])

    # Trend-Breite: Anteil Titel mit sauberem Auftrend.
    coherent = 0
    counted = 0
    for row in panel:
        er = row.get(er_key)
        above = row.get(above_200_key)
        if er is None and above is None:
            continue
        counted += 1
        if (er is not None and er >= 0.40) and (above is None or above >= 0.5):
            coherent += 1
    breadth = (coherent / counted) if counted else None

    # Renditedispersion: Standardabweichung der 1M-Renditen im Querschnitt.
    rets = [row.get(ret_key) for row in panel]
    rets = [r for r in rets if r is not None]
    disp = None
    if len(rets) >= 3:
        mu = sum(rets) / len(rets)
        disp = (sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5

    vol_lab = "mid"
    if med_vol is not None:
        vol_lab = "low" if med_vol < 0.22 else "stress" if med_vol > 0.45 else "mid"
    trend_lab = "mixed"
    if breadth is not None:
        trend_lab = "coherent" if breadth >= 0.55 else "incoherent" if breadth <= 0.30 else "mixed"
    disp_lab = "mid"
    if disp is not None:
        disp_lab = "high" if disp > 18.0 else "low" if disp < 7.0 else "mid"

    return RegimeSnapshot(vol_lab, trend_lab, disp_lab, med_vol, breadth, disp, n)
