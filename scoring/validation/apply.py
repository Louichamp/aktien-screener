"""Brücke von der Offline-Kalibrierung zurück in die Produktions-Gewichte.

`calibrated_composites()` ersetzt das technical_rating-Composite durch die
empirisch hergeleiteten Gewichte aus `data/signal_ic.json` — ABER nur, wenn die
Datei existiert UND opt-in aktiviert ist (`SIGNAL_IC_WEIGHTS=1`). Ohne beides
bleibt das Verhalten Bit-für-Bit identisch zum Prior. So fließt empirische
Evidenz nur nach bewusster Freigabe ein; ein fehlerhaftes/veraltetes IC-File
kann die Produktion nicht still verändern.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..composites import DEFAULT_COMPOSITES

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "signal_ic.json"


def calibrated_composites(base: dict[str, dict[str, float]] | None = None,
                          *, path: str | os.PathLike | None = None,
                          force: bool = False) -> dict[str, dict[str, float]]:
    """Liefert Composites mit (optional) evidenzbasiertem technical_rating.

    Aktiv nur bei `force=True` oder `SIGNAL_IC_WEIGHTS=1` UND vorhandener, valider
    Datei mit `recommended_weights.technical_rating`, deren Slug-Menge exakt dem
    Prior entspricht (Schutz gegen veraltete/halbe Files). Sonst: Prior unverändert.
    """
    base = base or DEFAULT_COMPOSITES
    if not (force or os.getenv("SIGNAL_IC_WEIGHTS") == "1"):
        return base
    p = Path(path) if path else _DEFAULT_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        rec = data["recommended_weights"]["technical_rating"]
    except (OSError, KeyError, ValueError):
        return base
    rec = {k: float(v) for k, v in rec.items() if not k.startswith("_")}
    prior_tr = base["technical_rating"]
    if set(rec) != set(prior_tr) or not rec:        # Slug-Menge muss exakt passen
        return base
    merged = dict(base)
    merged["technical_rating"] = rec
    return merged
