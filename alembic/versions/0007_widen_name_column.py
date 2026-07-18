"""name-Spalte auf 255 Zeichen verbreitern (Depositary-Shares-/Preferred-Namen)

Revision ID: 0007_widen_name
Revises: 0006_drop_unused_gin
Create Date: 2026-07-18

VARCHAR(128) crashte den täglichen compute_scores.py-Lauf live:
StringDataRightTruncationError bei "First Citizens BancShares, Inc.
Depositary Shares, each representing a 1/40th interest in a share of 6.625%
Non-Cumulative Perpetual Preferred Stock, Series E" (166 Zeichen, Ticker
FCNCN). Ein einziger zu langer Name brach die gesamte Transaktion und damit
den kompletten Tageslauf (drei Tage in Folge fehlgeschlagen).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_widen_name"
down_revision: Union[str, None] = "0006_drop_unused_gin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("screener_rows", "name",
                    existing_type=sa.String(length=128),
                    type_=sa.String(length=255))


def downgrade() -> None:
    op.alter_column("screener_rows", "name",
                    existing_type=sa.String(length=255),
                    type_=sa.String(length=128))
