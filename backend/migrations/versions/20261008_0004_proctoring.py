"""digital proctor: face templates (demo), snapshots, proctor signals

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-08 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "biometric_templates",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("nonce", sa.LargeBinary(), nullable=True),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("enrollments", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "attempt_snapshots",
        sa.Column(
            "attempt_id", sa.Uuid(), sa.ForeignKey("attempts.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "candidate_id",
            sa.Uuid(),
            sa.ForeignKey("candidate_profiles.user_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("jpeg", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("proctored", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("identity", sa.JSON(), nullable=True))
    with op.batch_alter_table("attempt_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("proctor", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("attempt_items", schema=None) as batch_op:
        batch_op.drop_column("proctor")
    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.drop_column("identity")
        batch_op.drop_column("proctored")
    op.drop_table("attempt_snapshots")
    op.drop_table("biometric_templates")
