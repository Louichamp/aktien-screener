"""Statistische Kurs-Prognose ohne torch (geometrische Brownsche Bewegung).

Schätzt aus den echten Log-Renditen der Kurshistorie Drift (μ) und Volatilität
(σ) und projiziert daraus geschlossen-form ein log-normales Konfidenzband:

    mean(t)  = S0 · exp(μ·t)
    upper(t) = S0 · exp(μ·t + z·σ·√t)
    lower(t) = S0 · exp(μ·t − z·σ·√t)

Das Band weitet sich mit √t und ist je Instrument unterschiedlich breit (echte
Vola) — genau das, was der Tearsheet-Kanal visualisiert. Kostenlos, deterministisch
und schnell genug für 5.000+ Titel. Gleiche Schnittstelle wie `KronosForecaster`
(`async forecast(snap, horizon)`), daher per `FORECAST_BACKEND` austauschbar.
"""
from __future__ import annotations

import math
import os
from datetime import date, timedelta
from typing import Any

from screener.pipeline import MarketSnapshot


def _business_days(n: int, start: date | None = None) -> list[str]:
    out: list[str] = []
    d = start or date.today()
    while len(out) < n:
        d += timedelta(days=1)
        if d.weekday() < 5:                     # Mo–Fr
            out.append(d.isoformat())
    return out


class StatisticalForecaster:
    """GBM-Forecast aus historischen Log-Renditen (kein ML, kein Key, kein torch)."""

    def __init__(self, *, horizon: int = 30, z: float | None = None,
                 lookback: int | None = None, max_daily_drift: float | None = None) -> None:
        self.horizon = horizon
        self.z = z if z is not None else float(os.getenv("FORECAST_Z", "1.28"))   # ~80 %
        self.lookback = lookback or int(os.getenv("FORECAST_LOOKBACK", "180"))
        # Drift kappen, damit Hochmomentum-Titel nicht absurd extrapolieren.
        self.max_daily_drift = (max_daily_drift if max_daily_drift is not None
                                else float(os.getenv("FORECAST_MAX_DAILY_DRIFT", "0.006")))

    async def aclose(self) -> None:
        return None

    def _estimate(self, closes: list[float]) -> tuple[float, float, float]:
        """Robuste Schätzung von Drift μ, Volatilität σ und Modell-Konfidenz.

        Drei Robustheitsstufen gegenüber der naiven Mittelwert-Drift:
          1. Winsorizing der Log-Renditen (±25 %) → ein Fehl-Tick/nicht-adjustierter
             Split sprengt weder σ noch μ.
          2. Drift-Signifikanz-Shrinkage: μ wird nur extrapoliert, soweit es
             statistisch von Null unterscheidbar ist (t = μ·√n/σ). Faktor
             t²/(t²+1) → bei insignifikanter Drift projiziert das Modell ~flach
             statt Rauschen in die Zukunft zu verlängern (institutionelle Praxis).
          3. Konfidenz aus Vola-Niveau × Stichprobengröße.
        """
        rets = [math.log(closes[i] / closes[i - 1])
                for i in range(1, len(closes))
                if closes[i] > 0 and closes[i - 1] > 0]
        rets = rets[-self.lookback:]
        n = len(rets)
        if n < 2:
            return 0.0, 0.01, 0.0
        rets = [max(-0.25, min(0.25, r)) for r in rets]        # Winsorizing
        mu = sum(rets) / n
        var = sum((r - mu) ** 2 for r in rets) / (n - 1)
        sigma = math.sqrt(max(var, 1e-9))

        # Drift-Signifikanz (t-Statistik des Mittelwerts) → Shrinkage gegen 0.
        se = sigma / math.sqrt(n)
        t = abs(mu) / se if se > 0 else 0.0
        mu *= t * t / (t * t + 1.0)
        mu = max(-self.max_daily_drift, min(self.max_daily_drift, mu))

        # Konfidenz: niedrige Jahresvola und große Stichprobe → vertrauenswürdiger.
        sigma_ann = sigma * math.sqrt(252.0)
        conf_vol = max(0.0, 1.0 - min(sigma_ann / 0.80, 1.0))
        conf_n = n / (n + 30.0)
        confidence = conf_vol * conf_n
        return mu, sigma, confidence

    async def forecast(self, snap: MarketSnapshot, *, horizon: int | None = None) -> dict[str, Any]:
        h = horizon or self.horizon
        closes = [c.c for c in snap.candles if c.c and c.c > 0]
        if len(closes) < 20:
            return {}
        mu, sigma, confidence = self._estimate(closes)
        s0 = snap.price or closes[-1]
        ts = _business_days(h)
        mean_path, upper, lower = [], [], []
        for t in range(1, h + 1):
            drift = mu * t
            band = self.z * sigma * math.sqrt(t)
            mean_path.append(round(s0 * math.exp(drift), 4))
            upper.append(round(s0 * math.exp(drift + band), 4))
            lower.append(round(s0 * math.exp(drift - band), 4))
        return {
            "timestamps": ts,
            "mean_path": mean_path,
            "upper_band": upper,
            "lower_band": lower,
            "direction": "up" if mean_path[-1] >= s0 else "down",
            "confidence": round(confidence, 3),
            "method": "statistical",
        }
