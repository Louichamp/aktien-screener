"""Leichtgewichtiger asynchroner TTL-Cache (In-Memory, pro Prozess).

Wird für den News-Endpunkt genutzt: schnelles Hin- und Herwechseln zwischen
Aktien im Frontend soll nicht jedes Mal eine FMP-Anfrage auslösen. Bewusst
dependency-frei; für horizontale Skalierung lässt sich dieselbe Schnittstelle
später gegen Redis tauschen.
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any


class TTLCache:
    """Async TTL-Cache mit `get_or_set`. Nicht-blockierend: die (langsame)
    Factory läuft außerhalb jeglichen Locks."""

    def __init__(self, ttl_seconds: float = 300.0, max_entries: int = 2048) -> None:
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        hit = self._store.get(key)
        if hit is None:
            return None
        expires_at, value = hit
        if expires_at <= time.monotonic():
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        # Einfache Größenbegrenzung: bei Überlauf abgelaufene Einträge ausmisten.
        if len(self._store) >= self.max_entries:
            now = time.monotonic()
            for k in [k for k, (exp, _) in self._store.items() if exp <= now]:
                self._store.pop(k, None)
            if len(self._store) >= self.max_entries:           # immer noch voll -> ältesten raus
                oldest = min(self._store, key=lambda k: self._store[k][0])
                self._store.pop(oldest, None)
        self._store[key] = (time.monotonic() + self.ttl, value)

    async def get_or_set(self, key: str, factory: Callable[[], Awaitable[Any]]) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = await factory()
        self.set(key, value)
        return value
