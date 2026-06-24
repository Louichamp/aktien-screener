"""DI-Verdrahtung für die API: Engine-Lifespan + Session pro Request.

Engine und Session-Factory leben im `app.state` (ein Pool pro Prozess). Der
`get_session`-Dependency öffnet je Request eine read-only-orientierte Session
und schließt sie sauber wieder.
"""
from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infrastructure.database.config import (create_engine, create_session_factory,
                                            init_models)
from .cache import TTLCache

log = logging.getLogger("screener.api")


def _build_news_provider() -> Any | None:
    """Provider für Live-News. Default Yahoo (gratis); `fmp` braucht einen Key.

    Über NEWS_PROVIDER bzw. DATA_PROVIDER steuerbar; Yahoo liefert News ohne Key.
    """
    name = os.getenv("NEWS_PROVIDER", os.getenv("DATA_PROVIDER", "yahoo")).lower()
    if name == "fmp" and not os.getenv("FMP_API_KEY"):
        return None
    try:
        from infrastructure.providers import build_market_data_provider
        return build_market_data_provider(name)
    except Exception as exc:                       # Netz/Import -> News deaktiviert
        log.warning("News-Provider nicht verfügbar: %s", exc)
        return None


def make_lifespan(database_url: str | None = None, *, create_schema: bool = False):
    """Erzeugt einen Lifespan-Handler, der Engine/Session-Factory verwaltet.

    `create_schema=True` legt das Schema beim Start an (nur Dev/Test; in
    Produktion über Alembic-Migrationen).
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(database_url)
        if create_schema:
            await init_models(engine)
        app.state.db_engine = engine
        app.state.sessionmaker = create_session_factory(engine)
        app.state.news_provider = _build_news_provider()
        app.state.news_cache = TTLCache(float(os.getenv("NEWS_CACHE_TTL", "300")))
        try:
            yield
        finally:
            provider = getattr(app.state, "news_provider", None)
            if provider is not None and hasattr(provider, "aclose"):
                await provider.aclose()
            await engine.dispose()

    return lifespan


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


def get_news_provider(request: Request) -> Any | None:
    return getattr(request.app.state, "news_provider", None)


def get_news_cache(request: Request) -> TTLCache:
    cache = getattr(request.app.state, "news_cache", None)
    if cache is None:                              # Fallback (z.B. Tests ohne Lifespan)
        cache = TTLCache()
        request.app.state.news_cache = cache
    return cache
