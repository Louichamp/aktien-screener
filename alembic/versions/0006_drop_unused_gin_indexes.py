"""GIN-Indizes auf JSONB-Passthrough-Spalten entfernen (Storage-Deckel Postgres Free Tier)

Revision ID: 0006_drop_unused_gin
Revises: 0005_data_as_of
Create Date: 2026-07-11

api/queries.py filtert nie über JSONB-Containment (`@>`/`?`) auf drivers,
targets, forecast_history oder price_history — es sind reine Passthrough-
Payloads fürs Tearsheet, nie Teil einer WHERE-Bedingung. GIN-Indizes auf
Text-/Array-lastigem JSONB sind häufig GRÖSSER als die Daten selbst und damit
auf einem 0.5GB-Free-Tier reiner Overhead ohne Query-Nutzen.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0006_drop_unused_gin"
down_revision: Union[str, None] = "0005_data_as_of"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GIN_INDEXES = [
    "ix_screener_rows_drivers_gin",
    "ix_screener_rows_targets_gin",
    "ix_screener_rows_forecast_gin",
    "ix_screener_rows_pricehist_gin",
]


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return                        # SQLite hat diese Indizes nie angelegt
    for name in _GIN_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.create_index("ix_screener_rows_drivers_gin", "screener_rows", ["drivers"],
                    postgresql_using="gin")
    op.create_index("ix_screener_rows_targets_gin", "screener_rows", ["targets"],
                    postgresql_using="gin")
    op.create_index("ix_screener_rows_forecast_gin", "screener_rows", ["forecast_history"],
                    postgresql_using="gin")
    op.create_index("ix_screener_rows_pricehist_gin", "screener_rows", ["price_history"],
                    postgresql_using="gin")
