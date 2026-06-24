"""Stammdaten (name/sector/country/asset_class), dividend_yield, rating + Indizes

Revision ID: 0002_company_meta
Revises: 0001_initial
Create Date: 2026-06-18

Ergänzt die Anzeige-/Filterspalten für das erweiterte Dashboard und die dazu
passenden B-Tree-Indizes (Branche, Land, Anlageklasse, Rating, Name, Dividende).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_company_meta"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("screener_rows", sa.Column("name", sa.String(length=128), nullable=True))
    op.add_column("screener_rows", sa.Column("sector", sa.String(length=64), nullable=True))
    op.add_column("screener_rows", sa.Column("country", sa.String(length=48), nullable=True))
    op.add_column("screener_rows", sa.Column("asset_class", sa.String(length=16), nullable=True))
    op.add_column("screener_rows",
                  sa.Column("dividend_yield", sa.Numeric(precision=8, scale=5), nullable=True))
    op.add_column("screener_rows", sa.Column("rating", sa.String(length=24), nullable=True))

    op.create_index("ix_screener_rows_sector", "screener_rows", ["sector"])
    op.create_index("ix_screener_rows_country", "screener_rows", ["country"])
    op.create_index("ix_screener_rows_asset_class", "screener_rows", ["asset_class"])
    op.create_index("ix_screener_rows_rating", "screener_rows", ["rating"])
    op.create_index("ix_screener_rows_name", "screener_rows", ["name"])
    op.create_index("ix_screener_rows_dividend_yield", "screener_rows", ["dividend_yield"])


def downgrade() -> None:
    for name in ("ix_screener_rows_dividend_yield", "ix_screener_rows_name",
                 "ix_screener_rows_rating", "ix_screener_rows_asset_class",
                 "ix_screener_rows_country", "ix_screener_rows_sector"):
        op.drop_index(name, table_name="screener_rows")
    for col in ("rating", "dividend_yield", "asset_class", "country", "sector", "name"):
        op.drop_column("screener_rows", col)
