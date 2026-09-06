"""Wochen-Watchlist speichern.

Die Watchlist entsteht einmal pro Woche aus den bereits berechneten
Screener-Zeilen (screener/watchlist.py) und wird als fertiges Dokument
abgelegt. Bewusst als Verlauf, nicht als einzelne Zeile: So laesst sich
spaeter nachvollziehen, was an einem bestimmten Montag auf der Liste stand.

Revision ID: 0010_weekly_watchlist
Revises: 0009_data_quality
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0010_weekly_watchlist"
down_revision: Union[str, None] = "0009_data_quality"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSONB = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "weekly_watchlist",
        sa.Column("generated_at", sa.String(length=32), primary_key=True),
        sa.Column("week_label", sa.String(length=32), nullable=True),
        sa.Column("payload", _JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("n_candidates", sa.Integer(), nullable=True),
        sa.Column("universe_size", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_weekly_watchlist_created", "weekly_watchlist", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_weekly_watchlist_created", table_name="weekly_watchlist")
    op.drop_table("weekly_watchlist")
