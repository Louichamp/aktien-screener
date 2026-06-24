"""Screener: Zonen-/Level-Engine, Status-Klassifikation, Strategie-Tagging.

Der Import dieses Pakets entdeckt automatisch alle Zonen-Quellen-Plugins im
`sources`-Unterpaket (`@register_zone_source`), sodass die `ZoneEngine()` ohne
weitere Verdrahtung die volle Registry nutzt.
"""
from __future__ import annotations

from .zones import discover_zone_sources

# Auto-Discovery der Zonen-Quellen (idempotent dank Registry-Guard).
discover_zone_sources(f"{__name__}.sources")
