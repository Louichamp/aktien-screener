"""Screener-Lese-Endpunkte (API v1).

  GET /api/v1/screener            — gefilterte, sortierte, paginierte Tabelle
  GET /api/v1/screener/facets     — Distinct-Werte für die Filter-Dropdowns
  GET /api/v1/screener/{ticker}   — vollständige Detailsicht (Tearsheet)
  GET /api/v1/screener/{ticker}/news — Live-Nachrichten (FMP, optional)
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from .cache import TTLCache
from .dependencies import get_news_cache, get_news_provider, get_session
from .queries import (DEFAULT_SORT, ScreenerFilters, get_screener_row,
                      query_facets, query_screener_rows, query_summary)
from .schemas import (FacetsResponse, NewsItem, NewsResponse, ScreenerListResponse,
                      ScreenerRowDetailSchema, ScreenerRowSchema, SummaryResponse)


def _ticker_list(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    out = [t.strip().upper() for t in raw.split(",") if t.strip()]
    return out or None

router = APIRouter(prefix="/api/v1", tags=["screener"])

SortBy = Literal["ticker", "name", "sector", "country", "price", "dividend_yield",
                 "wlatar", "wlafar", "total_score", "rating", "status", "strategy",
                 "risk_class", "data_as_of", "updated_at"]
SortDir = Literal["asc", "desc"]


def filter_params(
    search: Annotated[str | None, Query(description="Suche in Name/Ticker")] = None,
    strategy: Annotated[str | None, Query(description="Filter: Strategie-Tag")] = None,
    risk_class: Annotated[str | None, Query(description="Filter: Risikoklasse")] = None,
    sector: Annotated[str | None, Query(description="Filter: Branche")] = None,
    country: Annotated[str | None, Query(description="Filter: Land")] = None,
    asset_class: Annotated[str | None, Query(description="Filter: Anlageklasse")] = None,
    status_: Annotated[str | None, Query(alias="status", description="Filter: Status")] = None,
    rating: Annotated[str | None, Query(description="Filter: Rating-Label")] = None,
    trend_long: Annotated[str | None, Query(description="Filter: langfr. Trend")] = None,
    trend_medium: Annotated[str | None, Query(description="Filter: mittelfr. Trend")] = None,
    min_total_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    min_wlatar: Annotated[int | None, Query(ge=0, le=10)] = None,
    min_wlafar: Annotated[int | None, Query(ge=0, le=10)] = None,
    min_dividend_yield: Annotated[float | None, Query(ge=0)] = None,
    max_risk_level: Annotated[int | None, Query(ge=1, le=5)] = None,
    tickers: Annotated[str | None, Query(description="Komma-Liste exakter Ticker (z.B. Favoriten)")] = None,
) -> ScreenerFilters:
    return ScreenerFilters(
        search=search, strategy=strategy, risk_class=risk_class, sector=sector,
        country=country, asset_class=asset_class, status=status_, rating=rating,
        trend_long=trend_long, trend_medium=trend_medium,
        min_total_score=min_total_score, min_wlatar=min_wlatar, min_wlafar=min_wlafar,
        min_dividend_yield=min_dividend_yield, max_risk_level=max_risk_level,
        tickers=_ticker_list(tickers))


@router.get("/screener", response_model=ScreenerListResponse, summary="Screener-Tabelle")
async def list_screener(
    session: Annotated[AsyncSession, Depends(get_session)],
    filters: Annotated[ScreenerFilters, Depends(filter_params)],
    sort_by: Annotated[SortBy, Query(description="Sortierspalte")] = DEFAULT_SORT,
    sort_dir: Annotated[SortDir, Query(description="Sortierrichtung")] = "desc",
    limit: Annotated[int, Query(ge=1, le=500, description="Seitengröße")] = 25,
    offset: Annotated[int, Query(ge=0, description="Versatz für Pagination")] = 0,
) -> ScreenerListResponse:
    rows, total = await query_screener_rows(
        session, filters, sort_by=sort_by, descending=(sort_dir == "desc"),
        limit=limit, offset=offset)
    return ScreenerListResponse(
        items=[ScreenerRowSchema.model_validate(r) for r in rows],
        total=total, limit=limit, offset=offset)


@router.get("/screener/facets", response_model=FacetsResponse, summary="Filter-Facetten")
async def screener_facets(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FacetsResponse:
    return FacetsResponse(**await query_facets(session))


@router.get("/screener/summary", response_model=SummaryResponse, summary="Marktbreite (gefiltert)")
async def screener_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
    filters: Annotated[ScreenerFilters, Depends(filter_params)],
) -> SummaryResponse:
    return SummaryResponse(**await query_summary(session, filters))


@router.get("/screener/{ticker}", response_model=ScreenerRowDetailSchema,
            summary="Instrument-Detail (Tearsheet)")
async def get_screener_detail(
    ticker: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ScreenerRowDetailSchema:
    row = await get_screener_row(session, ticker.upper())
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Unbekannter Ticker: {ticker}")
    return ScreenerRowDetailSchema.model_validate(row)


@router.get("/screener/{ticker}/news", response_model=NewsResponse,
            summary="Live-Nachrichten zum Instrument")
async def get_screener_news(
    ticker: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    provider: Annotated[Any | None, Depends(get_news_provider)],
    cache: Annotated[TTLCache, Depends(get_news_cache)],
    limit: Annotated[int, Query(ge=1, le=50)] = 15,
) -> NewsResponse:
    tk = ticker.upper()
    # 404, wenn der Ticker nicht im Universum ist (konsistent mit dem Detail-Endpunkt).
    if await get_screener_row(session, tk) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Unbekannter Ticker: {ticker}")
    if provider is None:
        return NewsResponse(ticker=tk, items=[],
                            note="News deaktiviert — FMP_API_KEY nicht gesetzt.")
    try:
        # Cache je (Ticker, limit): wiederholtes Hin-/Herwechseln trifft den Cache,
        # nicht die FMP-API (TTL via NEWS_CACHE_TTL, Default 5 Min).
        raw = await cache.get_or_set(f"{tk}:{limit}",
                                     lambda: provider.fetch_news(tk, limit=limit))
    except Exception:
        return NewsResponse(ticker=tk, items=[],
                            note="News-Abruf momentan nicht verfügbar.")
    return NewsResponse(ticker=tk, items=[NewsItem.model_validate(n) for n in raw])
