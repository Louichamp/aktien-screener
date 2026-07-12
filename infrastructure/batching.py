"""Generischer Batching-Helfer (früher Teil des arq-Workers, jetzt eigenständig).

Zustandslos und ohne Abhängigkeiten — nützlich überall, wo Listen in feste
Blockgrößen zerteilt werden müssen (z. B. gechunkte Provider-Fetches).
"""
from __future__ import annotations

from typing import Any


def batched(seq: list[Any], n: int) -> list[list[Any]]:
    """Teilt eine Liste in Batches der Größe `n` (letzter Batch ggf. kleiner)."""
    n = max(1, n)
    return [seq[i:i + n] for i in range(0, len(seq), n)]
