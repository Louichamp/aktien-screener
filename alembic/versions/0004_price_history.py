"""price_history (Verlaufs-Chart im Tearsheet)

Revision ID: 0004_price_history
Revises: 0003_scale_indexes
Create Date: 2026-06-19

Fügt die JSONB-Spalte `price_history` (jüngste Schlusskurse) hinzu, damit der
Tearsheet einen durchgängigen „Verlauf → Prognose"-Chart rendern kann.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004_price_history"
down_revision: Union[str, None] = "0003_scale_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONBVariant = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    # server_default="[]" bleibt erhalten (harmlos auf PG & SQLite; das Drop-
    # Default via alter_column ist auf SQLite nicht möglich und würde die
    # Versionsmarkierung zurückrollen).
    op.add_column("screener_rows",
                  sa.Column("price_history", JSONBVariant, nullable=False,
                            server_default="[]"))
    if op.get_bind().dialect.name == "postgresql":
        op.create_index("ix_screener_rows_pricehist_gin", "screener_rows",
                        ["price_history"], postgresql_using="gin")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("ix_screener_rows_pricehist_gin", table_name="screener_rows")
    op.drop_column("screener_rows", "price_history")
