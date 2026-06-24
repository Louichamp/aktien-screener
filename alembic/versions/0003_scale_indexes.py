"""Skalierungs-Indizes für 5.000+ Zeilen: Composites + pg_trgm-Volltextsuche

Revision ID: 0003_scale_indexes
Revises: 0002_company_meta
Create Date: 2026-06-19

* Composite-Indizes (sector|strategy|asset_class, total_score) für das häufigste
  Muster „filtere nach X, sortiere nach Gesamtscore".
* PostgreSQL: pg_trgm-Extension + GIN-Trigramm-Index auf `name` (und `ticker`),
  damit die Substring-Volltextsuche (ILIKE '%…%') auch bei 50k Zeilen in ms
  antwortet. Auf SQLite werden die PG-spezifischen Schritte übersprungen.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003_scale_indexes"
down_revision: Union[str, None] = "0002_company_meta"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COMPOSITES = [
    ("ix_screener_rows_sector_score", ["sector", "total_score"]),
    ("ix_screener_rows_strategy_score", ["strategy_tag", "total_score"]),
    ("ix_screener_rows_assetclass_score", ["asset_class", "total_score"]),
]
_TRGM = [
    ("ix_screener_rows_name_trgm", "name"),
    ("ix_screener_rows_ticker_trgm", "ticker"),
]


def upgrade() -> None:
    for name, cols in _COMPOSITES:
        op.create_index(name, "screener_rows", cols)

    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        for name, col in _TRGM:
            op.create_index(name, "screener_rows", [col],
                            postgresql_using="gin", postgresql_ops={col: "gin_trgm_ops"})


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for name, _ in _TRGM:
            op.drop_index(name, table_name="screener_rows")
    for name, _ in _COMPOSITES:
        op.drop_index(name, table_name="screener_rows")
