"""store PR changed line content

Revision ID: 0005_pr_file_line_content
Revises: 0004_pr_file_line_annotations
Create Date: 2026-07-07
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_pr_file_line_content"
down_revision = "0004_pr_file_line_annotations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pr_file_line_annotations", sa.Column("line_content", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("pr_file_line_annotations", "line_content")
