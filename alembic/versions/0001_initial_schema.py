"""Initiales Schema: status_memory + screener_rows inkl. GIN-/B-Tree-Indizes

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-17

Legt beide Tabellen an. Die drei JSONB-Spalten (strategy_tags, targets, drivers,
forecast_history) erhalten auf PostgreSQL native GIN-Indizes (jsonb_ops) für
schnelle Containment-/Key-Abfragen; die heißen Filter-/Sortierspalten
(strategy_tag, risikoklasse, total_score) erhalten B-Tree-Indizes.
Auf SQLite wird `postgresql_using="gin"` ignoriert (regulärer Index).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Nativer JSONB in Produktion, generisches JSON als SQLite-Fallback (eingefroren
# in der Migration, bewusst unabhängig vom evolvierenden Modellcode).
JSONBVariant = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "status_memory",
        sa.Column("ticker", sa.String(length=32), primary_key=True),
        sa.Column("current_status", sa.String(length=48), nullable=True),
        sa.Column("pending_status", sa.String(length=48), nullable=True),
        sa.Column("confirm_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "screener_rows",
        sa.Column("ticker", sa.String(length=32), primary_key=True),
        sa.Column("price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("strategy_tag", sa.String(length=32), nullable=True),
        sa.Column("strategy_tags", JSONBVariant, nullable=False),
        sa.Column("status", sa.String(length=48), nullable=True),
        sa.Column("wlatar", sa.Integer(), nullable=True),
        sa.Column("wlafar", sa.Integer(), nullable=True),
        sa.Column("total_score", sa.Integer(), nullable=True),
        sa.Column("trend_long", sa.String(length=16), nullable=True),
        sa.Column("trend_medium", sa.String(length=16), nullable=True),
        sa.Column("risikoklasse", sa.String(length=16), nullable=True),
        sa.Column("chance_rarity", sa.String(length=16), nullable=True),
        sa.Column("targets", JSONBVariant, nullable=False),
        sa.Column("drivers", JSONBVariant, nullable=False),
        sa.Column("forecast_history", JSONBVariant, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # B-Tree auf die heißen Filter-/Sortierspalten
    op.create_index("ix_screener_rows_strategy_tag", "screener_rows", ["strategy_tag"])
    op.create_index("ix_screener_rows_risikoklasse", "screener_rows", ["risikoklasse"])
    op.create_index("ix_screener_rows_total_score", "screener_rows", ["total_score"])
    # GIN auf die JSONB-Spalten (PostgreSQL) — auf SQLite normaler Index
    op.create_index("ix_screener_rows_drivers_gin", "screener_rows", ["drivers"],
                    postgresql_using="gin")
    op.create_index("ix_screener_rows_targets_gin", "screener_rows", ["targets"],
                    postgresql_using="gin")
    op.create_index("ix_screener_rows_forecast_gin", "screener_rows", ["forecast_history"],
                    postgresql_using="gin")


def downgrade() -> None:
    for name in (
        "ix_screener_rows_forecast_gin", "ix_screener_rows_targets_gin",
        "ix_screener_rows_drivers_gin", "ix_screener_rows_total_score",
        "ix_screener_rows_risikoklasse", "ix_screener_rows_strategy_tag",
    ):
        op.drop_index(name, table_name="screener_rows")
    op.drop_table("screener_rows")
    op.drop_table("status_memory")
