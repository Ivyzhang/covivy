"""dashboard local users

Revision ID: 0007_dashboard_users
Revises: 0006_dashboard_settings
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_dashboard_users"
down_revision = "0006_dashboard_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dashboard_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.alter_column("user_sessions", "identity_id", nullable=True)
    op.add_column(
        "user_sessions",
        sa.Column("dashboard_user_id", sa.Integer(), sa.ForeignKey("dashboard_users.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_sessions", "dashboard_user_id")
    op.alter_column("user_sessions", "identity_id", nullable=False)
    op.drop_table("dashboard_users")
