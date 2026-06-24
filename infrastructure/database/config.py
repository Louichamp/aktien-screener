"""Datenbank-Konfiguration: async Engine + Session-Factory.

Produktion läuft auf PostgreSQL via asyncpg
(`postgresql+asyncpg://user:pass@host/db`). Für Tests kann jede async-URL
übergeben werden (z. B. `sqlite+aiosqlite://`).
"""
from __future__ import annotations

import os
from typing import Any

from sqlalchemy.ext.asyncio import (AsyncEngine, AsyncSession,
                                    async_sessionmaker, create_async_engine)

from .models import Base

DEFAULT_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/stockresearch")


def create_engine(url: str | None = None, *, echo: bool = False, **kwargs: Any) -> AsyncEngine:
    return create_async_engine(url or DEFAULT_URL, echo=echo, pool_pre_ping=True, **kwargs)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_models(engine: AsyncEngine) -> None:
    """Schema anlegen (Dev/Test; in Produktion via Alembic-Migrationen)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
