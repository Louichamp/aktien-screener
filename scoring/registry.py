"""Plugin-Registry für Score-Computor.

Der eigentliche Erweiterbarkeits-Mechanismus: `@register_score` registriert
eine Computor-Klasse beim Import, `discover_computors()` importiert alle Module
im `computors`-Paket. Ein neuer Score = eine neue Datei. Sonst nichts.
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Type

from .computor import ScoreComputor

SCORE_REGISTRY: dict[str, ScoreComputor] = {}


def register_score(cls: Type) -> Type:
    """Klassendekorator: instanziiert und registriert einen Computor."""
    inst = cls()
    slug = getattr(inst, "slug", "")
    if not slug:
        raise ValueError(f"{cls.__name__} hat keinen slug")
    if slug in SCORE_REGISTRY:
        raise ValueError(f"Doppelter Score-slug: {slug!r}")
    if not isinstance(inst, ScoreComputor):
        raise TypeError(f"{cls.__name__} erfüllt das ScoreComputor-Protokoll nicht")
    SCORE_REGISTRY[slug] = inst
    return cls


def discover_computors(package_name: str) -> None:
    """Importiert alle Module im angegebenen Paket -> Auto-Registrierung."""
    pkg = importlib.import_module(package_name)
    for mod in pkgutil.iter_modules(pkg.__path__):
        if not mod.name.startswith("_"):
            importlib.import_module(f"{package_name}.{mod.name}")


def get_computors() -> list[ScoreComputor]:
    """Alle registrierten Computor in Registrierungsreihenfolge."""
    return list(SCORE_REGISTRY.values())
