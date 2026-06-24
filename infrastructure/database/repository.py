"""Repository für den Screener-Zustand.

`StatusMemory` wird per atomarem Upsert (INSERT ... ON CONFLICT DO UPDATE)
geladen/geschrieben, damit der Worker zwischen Läufen konsistent auf die
Hysterese zugreift. Der Upsert ist dialekt-bewusst (PostgreSQL bzw. SQLite).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from screener.status import StatusMemory
from screener.row import ScreenerRow

from .models import ScreenerRowModel, StatusMemoryModel


# Gewichtung des Gesamtratings: Technik dominiert (Timing), Fundament stützt.
_TOTAL_W_TECH = 0.6
_TOTAL_W_FUND = 0.4


def compute_total_score(wlatar: float | None, wlafar: float | None) -> int | None:
    """Gewichteter Schnitt aus WLATAR/WLAFAR (je 0..10) -> Gesamtrating 0..100.

    Fehlt eine Komponente, zählt die vorhandene allein; fehlen beide -> None.
    """
    pairs = [(_TOTAL_W_TECH, wlatar), (_TOTAL_W_FUND, wlafar)]
    num = den = 0.0
    for w, v in pairs:
        if v is not None:
            num += w * v
            den += w
    return None if den == 0 else round(num / den * 10)


def rating_label(total_score: int | None) -> str | None:
    """Gesamtrating 0..100 -> handelbares Label (Louichamp-Rating)."""
    if total_score is None:
        return None
    if total_score >= 80:
        return "STARK KAUFEN"
    if total_score >= 65:
        return "KAUFEN"
    if total_score >= 50:
        return "HALTEN"
    if total_score >= 35:
        return "REDUZIEREN"
    return "VERKAUFEN"


def screener_row_to_values(row: ScreenerRow, *, price: float | None = None,
                           currency: str | None = None,
                           name: str | None = None, sector: str | None = None,
                           country: str | None = None, asset_class: str | None = None,
                           dividend_yield: float | None = None,
                           drivers: dict[str, Any] | None = None,
                           forecast_history: list[dict[str, Any]] | None = None,
                           price_history: list[float] | None = None,
                           forecast_return: float | None = None,
                           forecast_method: str | None = None,
                           data_as_of: str | None = None,
                           ) -> dict[str, Any]:
    """ScreenerRow (Domäne) + Stammdaten -> Spaltenwerte (Modell)."""
    total = compute_total_score(row.wlatar, row.wlafar)
    return dict(
        ticker=row.ticker,
        name=name,
        sector=sector,
        country=country,
        asset_class=asset_class,
        price=price,
        currency=currency,
        dividend_yield=dividend_yield,
        strategy_tag=row.strategy_tag,
        strategy_tags=list(row.strategy_tags),
        status=row.status,
        rating=rating_label(total),
        wlatar=None if row.wlatar is None else round(row.wlatar),
        wlafar=None if row.wlafar is None else round(row.wlafar),
        total_score=total,
        trend_long=row.trend_long,
        trend_medium=row.trend_mid,
        risikoklasse=row.risk_class,
        chance_rarity=row.rarity,
        data_as_of=data_as_of,
        targets=dict(signal_aggr=row.signal_aggr, signal_kons=row.signal_kons,
                     stop_loss=row.stop_loss, target_1=row.target_1,
                     target_2=row.target_2, crv=row.crv,
                     chance=row.chance, chance_dots=row.chance_dots,
                     forecast_return=forecast_return, forecast_method=forecast_method),
        drivers=drivers or {"rationale": list(row.rationale)},
        forecast_history=forecast_history or [],
        price_history=list(price_history or []),
    )


class ScreenerRepository:
    """Atomare Persistenz für StatusMemory und ScreenerRow."""

    def __init__(self, engine: AsyncEngine) -> None:
        # Dialekt zur Konstruktionszeit festlegen -> richtiger Upsert-Konstruktor
        self._insert = (pg_insert if engine.sync_engine.dialect.name == "postgresql"
                        else sqlite_insert)

    # ---- StatusMemory ---------------------------------------------------
    async def get_status_memory(self, session: AsyncSession, ticker: str) -> StatusMemory | None:
        m = await session.get(StatusMemoryModel, ticker)
        if m is None:
            return None
        return StatusMemory(status=m.current_status, pending=m.pending_status,
                            pending_count=m.confirm_runs)

    async def upsert_status_memory(self, session: AsyncSession, ticker: str,
                                   memory: StatusMemory) -> None:
        values = dict(ticker=ticker, current_status=memory.status,
                      pending_status=memory.pending, confirm_runs=memory.pending_count)
        stmt = self._insert(StatusMemoryModel).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker"],
            set_=dict(current_status=stmt.excluded.current_status,
                      pending_status=stmt.excluded.pending_status,
                      confirm_runs=stmt.excluded.confirm_runs))
        await session.execute(stmt)

    # ---- ScreenerRow ----------------------------------------------------
    async def upsert_screener_row(self, session: AsyncSession, values: dict[str, Any]) -> None:
        stmt = self._insert(ScreenerRowModel).values(**values)
        update_cols = {k: getattr(stmt.excluded, k) for k in values if k != "ticker"}
        stmt = stmt.on_conflict_do_update(index_elements=["ticker"], set_=update_cols)
        await session.execute(stmt)

    async def get_screener_row(self, session: AsyncSession, ticker: str) -> ScreenerRowModel | None:
        return await session.get(ScreenerRowModel, ticker)

    async def list_screener_rows(self, session: AsyncSession,
                                 strategy_tag: str | None = None) -> list[ScreenerRowModel]:
        q = select(ScreenerRowModel)
        if strategy_tag:
            q = q.where(ScreenerRowModel.strategy_tag == strategy_tag)
        return list((await session.execute(q)).scalars().all())
