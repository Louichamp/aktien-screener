"""Tests für die Waisen-Erkennung in der Screener-Tabelle.

Waisen sind Zeilen, deren Ticker nicht mehr im Universum ist (Delisting,
Umbenennung, Wechsel der Listing-Quelle). Sie werden nie wieder beschrieben,
behalten ihren `data_as_of` für immer und verfälschen den ausgewiesenen
„ältesten Stand": Am 2026-09-05 schrieb der Lauf 5086 Zeilen, die DB hielt
5366 — die Differenz zog den ältesten Stand von 2026-08-23 auf 2026-07-14.
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from infrastructure.database.config import (create_engine, create_session_factory,
                                            init_models)
from infrastructure.database.models import ScreenerRowModel, StatusMemoryModel
from infrastructure.database.repository import ScreenerRepository


def _ago(days: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


@pytest_asyncio.fixture
async def repo_and_db():
    tmp = tempfile.TemporaryDirectory()
    engine = create_engine(f"sqlite+aiosqlite:///{Path(tmp.name) / 'orphans.db'}")
    await init_models(engine)
    sm = create_session_factory(engine)
    async with sm() as s:
        s.add_all([
            ScreenerRowModel(ticker="LIVE", data_as_of=_ago(1)),
            ScreenerRowModel(ticker="ALT_IM_UNIVERSUM", data_as_of=_ago(200)),
            ScreenerRowModel(ticker="WAISE", data_as_of=_ago(90)),
            ScreenerRowModel(ticker="WAISE_FRISCH", data_as_of=_ago(3)),
            ScreenerRowModel(ticker="WAISE_OHNE_DATUM", data_as_of=None),
        ])
        s.add(StatusMemoryModel(ticker="WAISE", current_status="Bodenbildung"))
        await s.commit()
    yield ScreenerRepository(engine), sm
    await engine.dispose()
    tmp.cleanup()


@pytest.mark.asyncio
async def test_findet_nur_alte_universumsfremde_zeilen(repo_and_db):
    repo, sm = repo_and_db
    keep = {"LIVE", "ALT_IM_UNIVERSUM"}
    async with sm() as s:
        orphans = set(await repo.find_orphans(s, keep, older_than_days=60))
    assert orphans == {"WAISE", "WAISE_OHNE_DATUM"}
    # Im Universum -> nie Waise, egal wie alt die Daten sind.
    assert "ALT_IM_UNIVERSUM" not in orphans
    # Nicht im Universum, aber frisch -> noch keine Waise (evtl. nur kurzzeitig
    # aus der Listing-Quelle gefallen).
    assert "WAISE_FRISCH" not in orphans


@pytest.mark.asyncio
async def test_loeschen_entfernt_zeile_und_hysterese(repo_and_db):
    repo, sm = repo_and_db
    async with sm() as s:
        n = await repo.delete_rows(s, ["WAISE"])
        await s.commit()
    assert n == 1
    async with sm() as s:
        assert await repo.get_screener_row(s, "WAISE") is None
        assert await repo.get_status_memory(s, "WAISE") is None
        assert await repo.get_screener_row(s, "LIVE") is not None


@pytest.mark.asyncio
async def test_leere_liste_loescht_nichts(repo_and_db):
    repo, sm = repo_and_db
    async with sm() as s:
        assert await repo.delete_rows(s, []) == 0
        assert await repo.get_screener_row(s, "LIVE") is not None
