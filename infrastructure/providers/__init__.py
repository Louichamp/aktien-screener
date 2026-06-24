"""Externe Datenquellen (Markt-/Fundamentaldaten).

Standard ist Yahoo Finance (kostenlos, kein Key, massentauglich). Über
`DATA_PROVIDER=fmp` lässt sich auf Financial Modeling Prep umschalten.
"""
from __future__ import annotations

import os
from typing import Any

from .fmp import FMPMarketDataProvider
from .universe import build_universe
from .yahoo import YahooMarketDataProvider

__all__ = ["FMPMarketDataProvider", "YahooMarketDataProvider",
           "build_universe", "build_market_data_provider"]


def build_market_data_provider(name: str | None = None, **kwargs: Any) -> Any:
    """Provider-Fabrik: `yahoo` (Default, gratis) oder `fmp` (Key nötig)."""
    name = (name or os.getenv("DATA_PROVIDER", "yahoo")).lower()
    if name == "fmp":
        return FMPMarketDataProvider(**kwargs)
    return YahooMarketDataProvider(**kwargs)
