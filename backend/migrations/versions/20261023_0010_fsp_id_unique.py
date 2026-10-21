"""Unique FSP ID per candidate profile

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-23 10:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("candidate_profiles", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_candidate_profiles_fsp_id"))
        batch_op.create_index(batch_op.f("ix_candidate_profiles_fsp_id"), ["fsp_id"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("candidate_profiles", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_candidate_profiles_fsp_id"))
        batch_op.create_index(batch_op.f("ix_candidate_profiles_fsp_id"), ["fsp_id"], unique=False)
