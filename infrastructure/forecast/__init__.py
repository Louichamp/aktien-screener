"""Prognose-Modelle.

Standard ist der statistische GBM-Forecaster (gratis, kein torch). Über
`FORECAST_BACKEND=kronos` wird das echte Kronos-PyTorch-Modell genutzt.
"""
from __future__ import annotations

import os
from typing import Any

from .statistical import StatisticalForecaster

__all__ = ["StatisticalForecaster", "KronosForecaster", "build_forecaster",
           "apply_forecasts"]


async def apply_forecasts(forecaster: Any, snaps: Any, *, horizon: int = 30) -> int:
    """Heftet jedem Snapshot seinen Forecast an (`snap.forecast`). Pro-Ticker
    fehlerisoliert. `snaps` darf ein Dict {ticker: snap} oder iterable sein."""
    items = snaps.values() if isinstance(snaps, dict) else snaps
    ok = 0
    for snap in items:
        try:
            fc = await forecaster.forecast(snap, horizon=horizon)
            if fc:
                snap.forecast = fc
                ok += 1
        except Exception:                         # ein Forecast darf den Lauf nie killen
            continue
    return ok


def __getattr__(name: str):                       # lazy: Kronos importiert torch erst bei Bedarf
    if name == "KronosForecaster":
        from .kronos import KronosForecaster
        return KronosForecaster
    raise AttributeError(name)


def build_forecaster(name: str | None = None, **kwargs: Any) -> Any:
    """Forecaster-Fabrik: `statistical` (Default, gratis) oder `kronos` (torch)."""
    name = (name or os.getenv("FORECAST_BACKEND", "statistical")).lower()
    if name == "kronos":
        from .kronos import KronosForecaster
        return KronosForecaster(**kwargs)
    return StatisticalForecaster(**kwargs)
