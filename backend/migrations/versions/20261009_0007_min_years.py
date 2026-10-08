"""required experience in searches and vacancies

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-09 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("searches", "vacancies"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column("min_years", sa.Float(), nullable=True))


def downgrade() -> None:
    for table in ("vacancies", "searches"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column("min_years")
