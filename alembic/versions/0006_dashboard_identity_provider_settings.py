"""dashboard identity provider settings

Revision ID: 0006_dashboard_settings
Revises: 0005_pr_file_line_content
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_dashboard_settings"
down_revision = "0005_pr_file_line_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("login", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("provider", "external_id", name="uq_external_identities_provider_id"),
    )
    op.create_table(
        "oauth_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("identity_id", sa.Integer(), sa.ForeignKey("external_identities.id"), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("identity_id", name="uq_oauth_tokens_identity"),
    )
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("identity_id", sa.Integer(), sa.ForeignKey("external_identities.id"), nullable=False),
        sa.Column("session_token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("session_token_hash", name="uq_user_sessions_token_hash"),
    )
    op.add_column(
        "repositories",
        sa.Column("provider", sa.String(length=32), server_default="github", nullable=False),
    )
    op.add_column("repositories", sa.Column("provider_repo_id", sa.String(length=255), nullable=True))
    op.create_unique_constraint(
        "uq_repositories_provider_repo_id", "repositories", ["provider", "provider_repo_id"]
    )
    op.create_table(
        "repository_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("patch_coverage_target", sa.Float(), nullable=False),
        sa.Column("project_coverage_target", sa.Float(), nullable=False),
        sa.Column(
            "ignore_paths",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("status_enabled", sa.Boolean(), nullable=False),
        sa.Column("comment_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("repository_id", name="uq_repository_settings_repo"),
    )


def downgrade() -> None:
    op.drop_table("repository_settings")
    op.drop_constraint("uq_repositories_provider_repo_id", "repositories", type_="unique")
    op.drop_column("repositories", "provider_repo_id")
    op.drop_column("repositories", "provider")
    op.drop_table("user_sessions")
    op.drop_table("oauth_tokens")
    op.drop_table("external_identities")
