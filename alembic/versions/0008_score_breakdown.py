"""Score-Aufschluesselung und Signalstaerke persistieren.

Die Score-Engine rechnet 13 Sub-Scores, von denen bisher nur die beiden
verdichteten Kennzahlen gespeichert wurden. Die Frage "warum 87?" war aus den
gespeicherten Daten damit nicht beantwortbar. Beide Felder entstehen ohne
zusaetzlichen Rechenaufwand aus ohnehin vorhandenen Ergebnissen.

`signal_strength` ist eine eigene, indizierte Spalte statt eines Feldes im
JSONB: Danach soll gefiltert und sortiert werden koennen, und das geht auf
einer schmalen String-Spalte mit B-Tree-Index guenstiger als ueber einen
JSONB-Ausdruck.

Revision ID: 0008_score_breakdown
Revises: 0007_widen_name
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0008_score_breakdown"
down_revision: Union[str, None] = "0007_widen_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSONB = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.add_column("screener_rows",
                  sa.Column("score_breakdown", _JSONB, nullable=False,
                            server_default=sa.text("'{}'")))
    op.add_column("screener_rows",
                  sa.Column("signal_strength", sa.String(length=16), nullable=True))
    op.create_index("ix_screener_rows_signal_strength", "screener_rows",
                    ["signal_strength"])
    # Haeufigstes Muster der neuen Ansicht: "nur starke Signale, nach Gesamtscore".
    op.create_index("ix_screener_rows_signal_score", "screener_rows",
                    ["signal_strength", "total_score"])


def downgrade() -> None:
    op.drop_index("ix_screener_rows_signal_score", table_name="screener_rows")
    op.drop_index("ix_screener_rows_signal_strength", table_name="screener_rows")
    op.drop_column("screener_rows", "signal_strength")
    op.drop_column("screener_rows", "score_breakdown")
