"""store PR file-level patch coverage

Revision ID: 0003_pr_file_annotations
Revises: 0002_bigint_ids
Create Date: 2026-07-07
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_pr_file_annotations"
down_revision = "0002_bigint_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pr_file_annotations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("annotation_id", sa.Integer(), sa.ForeignKey("pr_annotations.id"), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("patch_covered_lines", sa.Integer(), nullable=False),
        sa.Column("patch_total_lines", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("pr_file_annotations")
