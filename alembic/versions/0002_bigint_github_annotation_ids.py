"""use bigint for GitHub annotation ids

Revision ID: 0002_bigint_ids
Revises: 0001_initial
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_bigint_ids"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "pr_annotations",
        "github_comment_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )
    op.alter_column(
        "pr_annotations",
        "github_check_run_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "pr_annotations",
        "github_check_run_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
    op.alter_column(
        "pr_annotations",
        "github_comment_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
