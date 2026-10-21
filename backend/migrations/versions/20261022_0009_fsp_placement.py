"""FSP placement: fsp-friendly vacancies, FSP alerts for searches, hired status

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-22 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("vacancies", schema=None) as batch_op:
        batch_op.add_column(sa.Column("fsp_friendly", sa.Boolean(), nullable=False, server_default="0"))
    with op.batch_alter_table("searches", schema=None) as batch_op:
        batch_op.add_column(sa.Column("fsp_friendly", sa.Boolean(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("notify_fsp", sa.Boolean(), nullable=False, server_default="0"))
    with op.batch_alter_table("invitations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("hired_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "fsp_match_notices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("search_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("emailed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["search_id"], ["searches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidate_profiles.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("search_id", "candidate_id"),
    )
    op.create_index("ix_fsp_match_notices_search_id", "fsp_match_notices", ["search_id"])
    op.create_index("ix_fsp_match_notices_created_at", "fsp_match_notices", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_fsp_match_notices_created_at", table_name="fsp_match_notices")
    op.drop_index("ix_fsp_match_notices_search_id", table_name="fsp_match_notices")
    op.drop_table("fsp_match_notices")
    with op.batch_alter_table("invitations", schema=None) as batch_op:
        batch_op.drop_column("hired_at")
    with op.batch_alter_table("searches", schema=None) as batch_op:
        batch_op.drop_column("notify_fsp")
        batch_op.drop_column("fsp_friendly")
    with op.batch_alter_table("vacancies", schema=None) as batch_op:
        batch_op.drop_column("fsp_friendly")
