"""store PR file source content

Revision ID: 0008_pr_file_source_content
Revises: 0007_dashboard_users
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_pr_file_source_content"
down_revision = "0007_dashboard_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pr_file_annotations", sa.Column("source_content", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("pr_file_annotations", "source_content")
