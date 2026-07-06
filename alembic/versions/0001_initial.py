"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("github_user_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("login", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "installations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("github_installation_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "repositories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("installation_id", sa.Integer(), sa.ForeignKey("installations.id"), nullable=True),
        sa.Column("github_repo_id", sa.Integer(), nullable=True, unique=True),
        sa.Column("owner", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=511), nullable=False),
        sa.Column("default_branch", sa.String(length=255), nullable=False),
        sa.Column("private", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("upload_token_hash", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("owner", "name", name="uq_repositories_owner_name"),
    )
    op.create_table(
        "commits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("sha", sa.String(length=64), nullable=False),
        sa.Column("branch", sa.String(length=255), nullable=True),
        sa.Column("parent_sha", sa.String(length=64), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("author_name", sa.String(length=255), nullable=True),
        sa.Column("author_email", sa.String(length=255), nullable=True),
        sa.Column("committed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("repository_id", "sha", name="uq_commits_repository_sha"),
    )
    op.create_table(
        "pull_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("github_pr_number", sa.Integer(), nullable=False),
        sa.Column("head_sha", sa.String(length=64), nullable=False),
        sa.Column("base_sha", sa.String(length=64), nullable=True),
        sa.Column("base_branch", sa.String(length=255), nullable=True),
        sa.Column("head_branch", sa.String(length=255), nullable=True),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "repository_id", "github_pr_number", name="uq_pull_requests_repo_number"
        ),
    )
    op.create_table(
        "uploads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("commit_id", sa.Integer(), sa.ForeignKey("commits.id"), nullable=False),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("uploader", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "coverage_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("commit_id", sa.Integer(), sa.ForeignKey("commits.id"), nullable=False),
        sa.Column("upload_id", sa.Integer(), sa.ForeignKey("uploads.id"), nullable=False),
        sa.Column("line_rate", sa.Float(), nullable=False),
        sa.Column("branch_rate", sa.Float(), nullable=True),
        sa.Column("covered_lines", sa.Integer(), nullable=False),
        sa.Column("total_lines", sa.Integer(), nullable=False),
        sa.Column("covered_branches", sa.Integer(), nullable=True),
        sa.Column("total_branches", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "file_coverages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("coverage_reports.id"), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("line_rate", sa.Float(), nullable=False),
        sa.Column("branch_rate", sa.Float(), nullable=True),
        sa.Column("covered_lines", sa.Integer(), nullable=False),
        sa.Column("total_lines", sa.Integer(), nullable=False),
    )
    op.create_table(
        "line_coverages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("file_coverage_id", sa.Integer(), sa.ForeignKey("file_coverages.id"), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("branch", sa.Boolean(), nullable=False),
        sa.Column("condition_coverage", sa.String(length=255), nullable=True),
    )
    op.create_table(
        "pr_annotations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pull_request_id", sa.Integer(), sa.ForeignKey("pull_requests.id"), nullable=False),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("coverage_reports.id"), nullable=False),
        sa.Column("patch_covered_lines", sa.Integer(), nullable=False),
        sa.Column("patch_total_lines", sa.Integer(), nullable=False),
        sa.Column("patch_line_rate", sa.Float(), nullable=False),
        sa.Column("github_comment_id", sa.BigInteger(), nullable=True),
        sa.Column("github_check_run_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(), nullable=False),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("locked_by", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    for table in [
        "jobs",
        "pr_annotations",
        "line_coverages",
        "file_coverages",
        "coverage_reports",
        "uploads",
        "pull_requests",
        "commits",
        "repositories",
        "installations",
        "accounts",
    ]:
        op.drop_table(table)
