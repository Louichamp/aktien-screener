"""Kronos: GBM-Forecast-Score — erwartete Rendite × Konfidenz."""
from __future__ import annotations

import math

from ..computor import BaseComputor
from ..context import InstrumentData, ScoringContext
from ..domain import ScoreResult
from ..normalization import band
from ..registry import register_score


@register_score
class ForecastComputor(BaseComputor):
    """Bewertet den statistischen GBM-Forecast (StatisticalForecaster):
    Positive Erwartungsrendite × Konfidenz (schmaleres Band = höhere Gewissheit)."""
    slug = "kronos"
    label = "Forecast"
    family = "momentum_flow"

    # Maximale Bandbreite, bei der die Konfidenz noch > 0 ist (50 % upper/lower Spread).
    _MAX_BAND_WIDTH = 0.50

    def compute(self, data: InstrumentData, ctx: ScoringContext) -> ScoreResult:
        fc = data.forecast
        if not fc:
            return self.missing("Kein Forecast vorhanden")

        mean_path = fc.get("mean_path") or []
        upper_band = fc.get("upper_band") or []
        lower_band = fc.get("lower_band") or []
        price = data.metric("close") or data.metric("price") or (mean_path[0] if mean_path else None)

        if not mean_path or price is None or price <= 0:
            return self.missing("Forecast unvollständig")

        target = mean_path[-1]
        expected_return = (target / price) - 1.0   # annualisierungsfreie Erwartungsrendite

        # Konfidenz: bevorzugt die vom Modell gelieferte (Vola × Stichprobe ×
        # Drift-Signifikanz). Fällt sonst auf die Bandbreite zurück (schmales
        # Band = geringe Unsicherheit). So bleibt der Score abwärtskompatibel.
        band_width = None
        model_conf = fc.get("confidence")
        if model_conf is not None:
            confidence = max(0.0, min(1.0, float(model_conf)))
        elif upper_band and lower_band and len(upper_band) == len(lower_band):
            band_width = (upper_band[-1] - lower_band[-1]) / price
            confidence = max(0.0, 1.0 - band_width / self._MAX_BAND_WIDTH)
        else:
            confidence = 0.5  # keine Information → neutrale Konfidenz

        # Basis-Score aus erwarteter Rendite (0..10 Skala)
        ret_score = band(expected_return, [
            (-0.30, 0), (-0.15, 2), (-0.05, 4), (0.0, 5),
            (0.05, 6), (0.10, 7.5), (0.20, 9), (0.35, 10)
        ])
        if ret_score is None:
            ret_score = 5.0

        # Niedrige Konfidenz zieht Score in Richtung 5 (neutral)
        score = ret_score * confidence + 5.0 * (1.0 - confidence)

        drivers = []
        ret_pct = expected_return * 100
        conf_pct = confidence * 100
        if expected_return >= 0.05:
            drivers.append(self.pos("positive_forecast",
                f"GBM-Ziel +{ret_pct:.1f} % in {len(mean_path)} Tagen (Konfidenz {conf_pct:.0f} %)",
                min(expected_return / 0.30, 1.0),
                expected_return=expected_return, confidence=confidence, target=target))
        elif expected_return <= -0.05:
            drivers.append(self.neg("negative_forecast",
                f"GBM-Ziel {ret_pct:.1f} % in {len(mean_path)} Tagen (Konfidenz {conf_pct:.0f} %)",
                min(-expected_return / 0.30, 1.0),
                expected_return=expected_return, confidence=confidence, target=target))

        if confidence < 0.30:
            drivers.append(self.neg("low_confidence",
                f"Hohes Konfidenzband — Prognose unsicher (Konfidenz {conf_pct:.0f} %)",
                0.30 - confidence,
                confidence=confidence, band_width=band_width if upper_band else None))

        direction = fc.get("direction", "up" if expected_return >= 0 else "down")
        state = f"{direction} ({ret_pct:+.1f} %)"
        return self.result(score, state, drivers,
                           expected_return=expected_return, confidence=confidence,
                           target=target, horizon=len(mean_path))
