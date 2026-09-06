"""Lese-Queries für den Screener — Filterung, Sortierung und Paging in SQL.

Alle Operationen laufen auf Datenbank-Ebene (WHERE / ORDER BY / LIMIT / OFFSET),
nicht in Python: Das hält die Antwort auch bei 5.000+ Instrumenten in
Millisekunden — gestützt von B-Tree-/Composite-/GIN-Indizes (siehe models.py
+ Migrationen). Filter und COUNT teilen sich dieselben Bedingungen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from sqlalchemy import distinct, func, nulls_last, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only
from sqlalchemy.sql.elements import ColumnElement

from infrastructure.database.models import ScreenerRowModel as M

# Spalten, die die LISTEN-Antwort (`ScreenerRowSchema`) tatsächlich braucht.
# Ohne diese Einschränkung lädt `select(M)` auch die schweren JSONB-Spalten
# `drivers`, `forecast_history` und `price_history` — gemessen 8,5 KB pro Zeile,
# also ~4,1 MB je 500er-Seite, die aus Neon gelesen und übertragen werden und
# die das Listen-Schema anschließend verwirft. Nur die Detailsicht braucht sie.
_LIST_COLUMNS = (
    M.ticker, M.name, M.sector, M.country, M.asset_class, M.price, M.currency,
    M.dividend_yield, M.strategy_tag, M.strategy_tags, M.status, M.rating,
    M.wlatar, M.wlafar, M.total_score, M.trend_long, M.trend_medium,
    M.risikoklasse, M.chance_rarity, M.data_as_of, M.signal_strength,
    M.targets, M.updated_at,
)

# Whitelist sortierbarer Spalten: schützt vor SQL-Injection über `sort_by`.
SORTABLE: Final[dict[str, ColumnElement]] = {
    "ticker": M.ticker, "name": M.name, "sector": M.sector, "country": M.country,
    "price": M.price, "dividend_yield": M.dividend_yield, "wlatar": M.wlatar,
    "wlafar": M.wlafar, "total_score": M.total_score, "rating": M.rating,
    "status": M.status, "strategy": M.strategy_tag, "risk_class": M.risikoklasse,
    "data_as_of": M.data_as_of, "updated_at": M.updated_at,
    "signal_strength": M.signal_strength,
}

DEFAULT_SORT: Final[str] = "total_score"

_SIGNAL_LEVEL: Final[dict[str, int]] = {"schwach": 1, "moderat": 2, "stark": 3}

_RISK_LEVEL: Final[dict[str, int]] = {
    "sehr niedrig": 1, "niedrig": 2, "mittel": 3, "hoch": 4, "sehr hoch": 5,
}


@dataclass(slots=True)
class ScreenerFilters:
    """Alle unterstützten Filter (alle optional, kombinierbar)."""
    search: str | None = None
    strategy: str | None = None
    risk_class: str | None = None
    sector: str | None = None
    country: str | None = None
    asset_class: str | None = None
    status: str | None = None
    rating: str | None = None
    trend_long: str | None = None
    trend_medium: str | None = None
    min_total_score: int | None = None
    min_wlatar: int | None = None
    min_wlafar: int | None = None
    min_dividend_yield: float | None = None
    max_risk_level: int | None = None
    tickers: list[str] | None = None          # exakte Auswahl (z.B. Favoriten)
    rare_only: bool = False                    # selten/sehr selten + KAUFEN/STARK KAUFEN
    signal_strength: str | None = None         # stark | moderat | schwach
    min_signal: str | None = None              # mindestens diese Stufe


def _conditions(f: ScreenerFilters) -> list:
    """Baut die WHERE-Bedingungen — geteilt von Daten- und COUNT-Abfrage."""
    c: list = []
    if f.search:
        like = f"%{f.search.strip()}%"
        c.append(or_(M.name.ilike(like), M.ticker.ilike(like)))
    if f.strategy is not None:
        c.append(M.strategy_tag == f.strategy)
    if f.risk_class is not None:
        c.append(M.risikoklasse == f.risk_class)
    if f.sector is not None:
        c.append(M.sector == f.sector)
    if f.country is not None:
        c.append(M.country == f.country)
    if f.asset_class is not None:
        c.append(M.asset_class == f.asset_class)
    if f.status is not None:
        c.append(M.status == f.status)
    if f.rating is not None:
        c.append(M.rating == f.rating)
    if f.trend_long is not None:
        c.append(M.trend_long == f.trend_long)
    if f.trend_medium is not None:
        c.append(M.trend_medium == f.trend_medium)
    if f.min_total_score is not None:
        c.append(M.total_score >= f.min_total_score)
    if f.min_wlatar is not None:
        c.append(M.wlatar >= f.min_wlatar)
    if f.min_wlafar is not None:
        c.append(M.wlafar >= f.min_wlafar)
    if f.min_dividend_yield is not None:
        c.append(M.dividend_yield >= f.min_dividend_yield)
    if f.max_risk_level is not None:
        allowed = [lbl for lbl, lvl in _RISK_LEVEL.items() if lvl <= f.max_risk_level]
        c.append(M.risikoklasse.in_(allowed))
    if f.tickers:
        c.append(M.ticker.in_([t.upper() for t in f.tickers]))
    if f.signal_strength is not None:
        c.append(M.signal_strength == f.signal_strength)
    if f.min_signal is not None:
        # „mindestens moderat" ist die eigentlich nützliche Abfrage: Sie
        # blendet Treffer aus, die nur auf einer einzelnen Bedingung beruhen.
        allowed = [lbl for lbl, lvl in _SIGNAL_LEVEL.items()
                   if lvl >= _SIGNAL_LEVEL.get(f.min_signal, 0)]
        c.append(M.signal_strength.in_(allowed))
    if f.rare_only:
        c.append(M.chance_rarity.in_(["selten", "sehr selten"]))
        c.append(M.rating.in_(["KAUFEN", "STARK KAUFEN"]))
    return c


async def query_screener_rows(
    session: AsyncSession,
    filters: ScreenerFilters | None = None,
    *,
    sort_by: str = DEFAULT_SORT,
    descending: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[M], int]:
    """Gefilterte, sortierte, paginierte Zeilen + Gesamtzahl.

    `total` = COUNT nach Filterung, vor LIMIT/OFFSET (für „1–10 von N"). Beide
    Abfragen teilen die WHERE-Bedingungen; der COUNT läuft ohne Sub-SELECT.
    """
    conds = _conditions(filters or ScreenerFilters())

    total = await session.scalar(select(func.count()).select_from(M).where(*conds))

    col = SORTABLE.get(sort_by, SORTABLE[DEFAULT_SORT])
    direction = col.desc() if descending else col.asc()
    stmt = (select(M).where(*conds)
            .options(load_only(*_LIST_COLUMNS, raiseload=True))
            .order_by(nulls_last(direction), M.ticker.asc())
            .limit(limit).offset(offset))
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows), int(total or 0)


async def get_screener_row(session: AsyncSession, ticker: str) -> M | None:
    return await session.get(M, ticker)


async def _distinct(session: AsyncSession, col: ColumnElement) -> list[str]:
    rows = (await session.execute(
        select(distinct(col)).where(col.is_not(None)).order_by(col.asc()))).scalars().all()
    return [r for r in rows if r]


async def query_facets(session: AsyncSession):
    """Distinct-Werte je Filterspalte (für die Dropdowns) + Gesamtzahl."""
    total = await session.scalar(select(func.count()).select_from(M))
    return {
        "sectors": await _distinct(session, M.sector),
        "countries": await _distinct(session, M.country),
        "asset_classes": await _distinct(session, M.asset_class),
        "statuses": await _distinct(session, M.status),
        "strategies": await _distinct(session, M.strategy_tag),
        "risk_classes": await _distinct(session, M.risikoklasse),
        "ratings": await _distinct(session, M.rating),
        "total": int(total or 0),
    }


async def query_summary(session: AsyncSession, filters: ScreenerFilters | None = None) -> dict:
    """Marktbreite der GEFILTERTEN Menge: Anzahl je Rating + Schnitt-Gesamtscore
    + Datenabdeckung (ältester/neuester data_as_of — ISO-Strings sortieren
    lexikographisch korrekt, daher MIN/MAX direkt auf der String-Spalte).

    Zwei schlanke, indexierte Aggregat-Queries — auch bei 5.000+ in Millisekunden.
    """
    conds = _conditions(filters or ScreenerFilters())
    rows = (await session.execute(
        select(M.rating, func.count(), func.avg(M.total_score))
        .where(*conds).group_by(M.rating))).all()
    by_rating = {r: int(n) for r, n, _ in rows if r}
    total = sum(int(n) for _, n, _ in rows)
    # gewichteter Schnitt des Gesamtscores
    num = sum((avg or 0) * n for _, n, avg in rows if avg is not None)
    den = sum(n for _, n, avg in rows if avg is not None)

    oldest, newest = (await session.execute(
        select(func.min(M.data_as_of), func.max(M.data_as_of)).where(*conds))).one()

    return {"total": total, "by_rating": by_rating,
            "avg_total_score": round(num / den, 1) if den else None,
            "oldest_data_as_of": oldest, "newest_data_as_of": newest}
