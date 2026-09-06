"""Datenqualitaet je Instrument persistieren.

Ein Score von 87/100 sah bisher identisch aus, ob er auf zwoelf Jahren
lueckenloser Historie beruhte oder auf acht Wochen Kursen ohne jede
Fundamentalkennzahl. Gemessen an 250 Titeln reicht die Spanne von 46
(53 % Nulltage, 30 Tagesspruenge ueber 35 % — vermutlich fehlerhafte
Split-Bereinigung) bis 94.

Eigene Spalten statt eines JSONB-Feldes: Danach soll gefiltert und sortiert
werden ("nur belastbare Datenlage"), und das geht auf schmalen, indizierten
Spalten guenstiger. Die ausfuehrliche Begruendung je Titel liegt weiterhin
im JSONB der Detailsicht.

Revision ID: 0009_data_quality
Revises: 0008_score_breakdown
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_data_quality"
down_revision: Union[str, None] = "0008_score_breakdown"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("screener_rows",
                  sa.Column("data_quality", sa.Integer(), nullable=True))
    op.add_column("screener_rows",
                  sa.Column("data_quality_label", sa.String(length=16), nullable=True))
    op.create_index("ix_screener_rows_data_quality", "screener_rows", ["data_quality"])


def downgrade() -> None:
    op.drop_index("ix_screener_rows_data_quality", table_name="screener_rows")
    op.drop_column("screener_rows", "data_quality_label")
    op.drop_column("screener_rows", "data_quality")
