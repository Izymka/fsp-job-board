"""integrity signals and practical scenarios

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("attempt_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("kind", sa.String(length=16), nullable=False, server_default="item"))
        batch_op.add_column(sa.Column("away_ms", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("paste_attempts", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("copy_attempts", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("meta", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("score", sa.Double(), nullable=True))
    with op.batch_alter_table("candidate_profiles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("assessment_summary", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("candidate_profiles", schema=None) as batch_op:
        batch_op.drop_column("assessment_summary")
    with op.batch_alter_table("attempt_items", schema=None) as batch_op:
        for c in ("score", "meta", "copy_attempts", "paste_attempts", "away_ms", "kind"):
            batch_op.drop_column(c)
