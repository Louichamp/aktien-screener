"""SQLAlchemy-Modelle für den Screener-Zustand.

Flexible Metadaten (targets, drivers, Tag-Liste) liegen in nativen
PostgreSQL-`JSONB`-Spalten (performant + später indizierbar). Für Tests gibt
es eine generische JSON-Variante, sodass dieselben Modelle auf SQLite laufen.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Nativer JSONB-Typ in Produktion, generisches JSON nur als SQLite-Fallback (Tests)
JSONBType = JSONB().with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    pass


class StatusMemoryModel(Base):
    """Persistenter Hysterese-Zustand pro Ticker (atomar per Upsert)."""
    __tablename__ = "status_memory"

    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    current_status: Mapped[str | None] = mapped_column(String(48), nullable=True)
    pending_status: Mapped[str | None] = mapped_column(String(48), nullable=True)
    # Anzahl Läufe, die der pending-Kandidat schon besteht (Hysterese-Zähler)
    confirm_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ScreenerRowModel(Base):
    """UI-fertige Screener-Zeile pro Ticker."""
    __tablename__ = "screener_rows"

    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    # Stammdaten (für Anzeige & Filter): Name ist die primäre Anzeige-Spalte,
    # Ticker bleibt der Schlüssel und eine ein-/ausblendbare Spalte.
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True)      # Branche
    country: Mapped[str | None] = mapped_column(String(48), nullable=True)     # Land
    asset_class: Mapped[str | None] = mapped_column(String(16), nullable=True)  # Aktie/ETF/Krypto/Forex
    price: Mapped[float | None] = mapped_column(Numeric(18, 4, asdecimal=False), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    dividend_yield: Mapped[float | None] = mapped_column(
        Numeric(8, 5, asdecimal=False), nullable=True)                         # 0.025 = 2,5 %

    # Strategie-Tagging
    strategy_tag: Mapped[str | None] = mapped_column(String(32), nullable=True)
    strategy_tags: Mapped[list] = mapped_column(JSONBType, nullable=False, default=list)

    # Zustand & Ratings
    status: Mapped[str | None] = mapped_column(String(48), nullable=True)
    rating: Mapped[str | None] = mapped_column(String(24), nullable=True)      # KAUFEN/HALTEN/...
    wlatar: Mapped[int | None] = mapped_column(Integer, nullable=True)        # 0..10 (Badge)
    wlafar: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Gesamtrating 0..100: gewichteter Schnitt aus WLATAR/WLAFAR, beim Write-Back
    # vorberechnet -> direkt sortierbar (B-Tree-Index), kein JSONB-Zugriff nötig.
    total_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Trend & Klassen
    trend_long: Mapped[str | None] = mapped_column(String(16), nullable=True)
    trend_medium: Mapped[str | None] = mapped_column(String(16), nullable=True)
    risikoklasse: Mapped[str | None] = mapped_column(String(16), nullable=True)
    chance_rarity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Stand der zugrunde liegenden Daten (ISO) — pro Wert, für Rotation/Anzeige.
    data_as_of: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Flexible Metadaten als JSONB
    targets: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)   # signal/stop/kursziele/crv
    drivers: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)   # bull/bear/rationale
    # Kronos-Prognose als Zeitreihe: list[{timestamp, mean, upper, lower}] (30 Tage).
    forecast_history: Mapped[list] = mapped_column(JSONBType, nullable=False, default=list)
    # Jüngste Schlusskurse (für den Verlaufs-Chart im Tearsheet): list[float].
    price_history: Mapped[list] = mapped_column(JSONBType, nullable=False, default=list)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # --- Performance-Indizes -------------------------------------------------
    # B-Tree auf die heißen Filter-/Sortierspalten + GIN auf die JSONB-Spalten.
    # GIN (jsonb_ops) macht Containment-/Key-Abfragen (`@>`, `?`) im Live-Betrieb
    # schnell; auf SQLite (Tests) wird `postgresql_using` ignoriert -> B-Tree.
    __table_args__ = (
        Index("ix_screener_rows_strategy_tag", "strategy_tag"),
        Index("ix_screener_rows_risikoklasse", "risikoklasse"),
        Index("ix_screener_rows_total_score", "total_score"),
        Index("ix_screener_rows_sector", "sector"),
        Index("ix_screener_rows_country", "country"),
        Index("ix_screener_rows_asset_class", "asset_class"),
        Index("ix_screener_rows_rating", "rating"),
        Index("ix_screener_rows_name", "name"),
        Index("ix_screener_rows_dividend_yield", "dividend_yield"),
        Index("ix_screener_rows_data_as_of", "data_as_of"),
        # Composite-Indizes für das häufigste Muster „filtere nach X, sortiere
        # nach Gesamtscore" -> Index-only-Scan statt Sortier-Schritt bei 5.000+.
        Index("ix_screener_rows_sector_score", "sector", "total_score"),
        Index("ix_screener_rows_strategy_score", "strategy_tag", "total_score"),
        Index("ix_screener_rows_assetclass_score", "asset_class", "total_score"),
        # KEINE GIN-Indizes mehr auf drivers/targets/forecast_history/price_history:
        # api/queries.py filtert nie über JSONB-Containment (`@>`/`?`) auf diesen
        # Spalten — nur Passthrough-Payload fürs Tearsheet. GIN-Indizes auf
        # Text-/Array-lastigem JSONB sind oft GRÖSSER als die Daten selbst; auf dem
        # 0.5GB-Postgres-Free-Tier ist das reiner Overhead ohne Query-Nutzen
        # (entfernt in Migration 0006, s. storage_notes.md).
    )
