"""specialization directions in candidate profile

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08 19:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("candidate_profiles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("directions", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    with op.batch_alter_table("candidate_profiles", schema=None) as batch_op:
        batch_op.drop_column("directions")
