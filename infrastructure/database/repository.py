"""Repository für den Screener-Zustand.

`StatusMemory` wird per atomarem Upsert (INSERT ... ON CONFLICT DO UPDATE)
geladen/geschrieben, damit der Worker zwischen Läufen konsistent auf die
Hysterese zugreift. Der Upsert ist dialekt-bewusst (PostgreSQL bzw. SQLite).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
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


# Unterhalb dieser Datenqualität wird KEINE Empfehlung mehr ausgesprochen.
# Entspricht der Grenze zu „unzureichend" in screener/data_quality.py.
MIN_QUALITY_FOR_RATING = 60

RATING_UNCLEAR = "UNKLAR"


def rating_label(total_score: int | None,
                 data_quality: int | None = None) -> str | None:
    """Gesamtrating 0..100 -> handelbares Label (Louichamp-Rating).

    Reicht die Datengrundlage nicht, wird KEINE Empfehlung gegeben, sondern
    `UNKLAR`. Grund: Fehlt eine Komponente, rechnet `compute_total_score`
    mit der verbleibenden weiter — ein rein technischer Wert von 8,6/10 wurde
    so zu „86/100 STARK KAUFEN", ununterscheidbar von einem Titel mit
    vollständiger Grundlage. Im Volllauf vom 2026-09-06 betraf das 4161 von
    4906 Titeln; PLCI stand mit Datenqualität 31 und ohne eine einzige
    Fundamentalkennzahl auf STARK KAUFEN.

    Der Score selbst bleibt erhalten und wird weiter angezeigt — er ist
    ehrlich berechnet. Nur die Handlungsempfehlung entfällt, weil sie auf
    dieser Grundlage nicht zu verantworten ist.
    """
    if total_score is None:
        return None
    if data_quality is not None and data_quality < MIN_QUALITY_FOR_RATING:
        return RATING_UNCLEAR
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
                           score_breakdown: dict[str, Any] | None = None,
                           signal_strength: str | None = None,
                           data_quality: int | None = None,
                           data_quality_label: str | None = None,
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
        rating=rating_label(total, data_quality),
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
        score_breakdown=score_breakdown or {},
        signal_strength=signal_strength,
        data_quality=data_quality,
        data_quality_label=data_quality_label,
    )


def _as_utc(value: Any) -> datetime | None:
    """Zeitstempel robust nach UTC. PostgreSQL liefert hier ein `datetime`,
    SQLite (Tests, lokale Läufe) je nach Spaltentyp einen ISO-String — beides
    muss dieselbe Vergleichslogik durchlaufen."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


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

    async def get_status_memories(self, session: AsyncSession,
                                  tickers: list[str]) -> dict[str, StatusMemory]:
        """Hysterese für viele Ticker in EINER Abfrage.

        Zuvor lief pro Ticker ein eigenes `session.get()` — bei 5086 Titeln
        also 5086 Netzwerk-Roundtrips, nur um den vorherigen Status zu lesen.
        """
        if not tickers:
            return {}
        out: dict[str, StatusMemory] = {}
        # In Blöcken, damit die IN-Liste nicht die Parametergrenze sprengt.
        for i in range(0, len(tickers), 2000):
            chunk = tickers[i:i + 2000]
            rows = (await session.execute(
                select(StatusMemoryModel).where(
                    StatusMemoryModel.ticker.in_(chunk)))).scalars().all()
            for m in rows:
                out[m.ticker] = StatusMemory(status=m.current_status,
                                             pending=m.pending_status,
                                             pending_count=m.confirm_runs)
        return out

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

    async def upsert_screener_rows(self, session: AsyncSession,
                                   rows: list[dict[str, Any]]) -> None:
        """Viele Zeilen in EINER Anweisung schreiben.

        Der Write-Back lief bisher Zeile für Zeile, jede in einer eigenen
        SAVEPOINT-Klammer — also rund vier Netzwerk-Roundtrips pro Titel
        (SAVEPOINT, zwei Upserts, RELEASE). Bei 5086 Titeln sind das über
        20.000 Roundtrips zur Datenbank. Gemessen am Lauf vom 2026-09-05:
        die reine Rechenzeit betrug 2,5 Minuten, der Lauf dauerte 84 —
        der Rest war Wartezeit auf das Netz.

        Alle Zeilen müssen dieselben Spalten haben; `screener_row_to_values`
        garantiert das. PostgreSQL erlaubt 65535 Parameter je Anweisung, bei
        ~28 Spalten also gut 2300 Zeilen — der Aufrufer stückelt entsprechend.
        """
        if not rows:
            return
        stmt = self._insert(ScreenerRowModel).values(rows)
        update_cols = {k: getattr(stmt.excluded, k) for k in rows[0] if k != "ticker"}
        stmt = stmt.on_conflict_do_update(index_elements=["ticker"], set_=update_cols)
        await session.execute(stmt)

    async def upsert_status_memories(self, session: AsyncSession,
                                     memories: list[tuple[str, StatusMemory]]) -> None:
        """Hysterese-Zustände gebündelt schreiben (siehe upsert_screener_rows)."""
        if not memories:
            return
        values = [dict(ticker=tk, current_status=m.status, pending_status=m.pending,
                       confirm_runs=m.pending_count) for tk, m in memories]
        stmt = self._insert(StatusMemoryModel).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker"],
            set_=dict(current_status=stmt.excluded.current_status,
                      pending_status=stmt.excluded.pending_status,
                      confirm_runs=stmt.excluded.confirm_runs))
        await session.execute(stmt)

    async def get_screener_row(self, session: AsyncSession, ticker: str) -> ScreenerRowModel | None:
        return await session.get(ScreenerRowModel, ticker)

    async def find_orphans(self, session: AsyncSession, keep: set[str], *,
                           older_than_days: int = 60) -> list[str]:
        """Zeilen, die NICHT mehr im Universum sind und deren Daten alt sind.

        Solche Waisen entstehen, wenn ein Symbol aus dem Universum fällt
        (Delisting, Umbenennung, Änderung der Listing-Quelle): Sie werden nie
        wieder beschrieben, behalten ihren alten `data_as_of` für immer und
        verfälschen so den ausgewiesenen „ältesten Stand". Real gemessen am
        2026-09-05: Der Lauf schrieb 5086 Zeilen, die DB enthielt 5366 —
        die Differenz zog den ältesten Stand von 2026-08-23 auf 2026-07-14.

        Nur lesend. Das Löschen entscheidet der Aufrufer (`delete_rows`),
        weil ein kaputtes Universum sonst die halbe Tabelle mitnehmen könnte.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        rows = (await session.execute(
            select(ScreenerRowModel.ticker, ScreenerRowModel.data_as_of))).all()
        out: list[str] = []
        for ticker, as_of in rows:
            if ticker in keep:
                continue
            stamp = _as_utc(as_of)
            if stamp is None or stamp < cutoff:   # ohne Datum = nie geschrieben
                out.append(ticker)
        return out

    async def delete_rows(self, session: AsyncSession, tickers: list[str]) -> int:
        """Löscht die genannten Zeilen. Bewusst ohne eigene Sicherheitslogik —
        der Aufrufer muss die Liste geprüft haben (siehe `find_orphans`)."""
        if not tickers:
            return 0
        await session.execute(
            delete(StatusMemoryModel).where(StatusMemoryModel.ticker.in_(tickers)))
        res = await session.execute(
            delete(ScreenerRowModel).where(ScreenerRowModel.ticker.in_(tickers)))
        return int(res.rowcount or 0)

    async def list_screener_rows(self, session: AsyncSession,
                                 strategy_tag: str | None = None) -> list[ScreenerRowModel]:
        q = select(ScreenerRowModel)
        if strategy_tag:
            q = q.where(ScreenerRowModel.strategy_tag == strategy_tag)
        return list((await session.execute(q)).scalars().all())
