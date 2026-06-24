"""data_as_of (Stand der Daten pro Wert, für Rotation/Anzeige)

Revision ID: 0005_data_as_of
Revises: 0004_price_history
Create Date: 2026-06-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_data_as_of"
down_revision: Union[str, None] = "0004_price_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("screener_rows", sa.Column("data_as_of", sa.String(length=32), nullable=True))
    op.create_index("ix_screener_rows_data_as_of", "screener_rows", ["data_as_of"])


def downgrade() -> None:
    op.drop_index("ix_screener_rows_data_as_of", table_name="screener_rows")
    op.drop_column("screener_rows", "data_as_of")
