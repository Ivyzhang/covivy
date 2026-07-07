"""store PR changed line coverage

Revision ID: 0004_pr_file_line_annotations
Revises: 0003_pr_file_annotations
Create Date: 2026-07-07
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_pr_file_line_annotations"
down_revision = "0003_pr_file_annotations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pr_file_line_annotations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "file_annotation_id",
            sa.Integer(),
            sa.ForeignKey("pr_file_annotations.id"),
            nullable=False,
        ),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("covered", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("pr_file_line_annotations")
