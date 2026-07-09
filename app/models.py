from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def now() -> datetime:
    return datetime.utcnow()


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    github_user_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    login: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_external_identities_provider_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    login: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"
    __table_args__ = (UniqueConstraint("identity_id", name="uq_oauth_tokens_identity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_id: Mapped[int] = mapped_column(ForeignKey("external_identities.id"), nullable=False)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    scope: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class DashboardUser(Base):
    __tablename__ = "dashboard_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (UniqueConstraint("session_token_hash", name="uq_user_sessions_token_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_id: Mapped[int] = mapped_column(ForeignKey("external_identities.id"), nullable=True)
    dashboard_user_id: Mapped[int] = mapped_column(ForeignKey("dashboard_users.id"), nullable=True)
    session_token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class Installation(Base):
    __tablename__ = "installations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    github_installation_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint("owner", "name", name="uq_repositories_owner_name"),
        UniqueConstraint("provider", "provider_repo_id", name="uq_repositories_provider_repo_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    installation_id: Mapped[int] = mapped_column(ForeignKey("installations.id"), nullable=True)
    github_repo_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=True)
    provider: Mapped[str] = mapped_column(String(32), default="github", nullable=False)
    provider_repo_id: Mapped[str] = mapped_column(String(255), nullable=True)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(511), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(255), default="main", nullable=False)
    private: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    upload_token_hash: Mapped[str] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class RepositorySettings(Base):
    __tablename__ = "repository_settings"
    __table_args__ = (UniqueConstraint("repository_id", name="uq_repository_settings_repo"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), nullable=False)
    patch_coverage_target: Mapped[float] = mapped_column(Float, default=0.8, nullable=False)
    project_coverage_target: Mapped[float] = mapped_column(Float, default=0.8, nullable=False)
    ignore_paths: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=list, nullable=False
    )
    status_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    comment_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class Commit(Base):
    __tablename__ = "commits"
    __table_args__ = (UniqueConstraint("repository_id", "sha", name="uq_commits_repository_sha"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), nullable=False)
    sha: Mapped[str] = mapped_column(String(64), nullable=False)
    branch: Mapped[str] = mapped_column(String(255), nullable=True)
    parent_sha: Mapped[str] = mapped_column(String(64), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=True)
    author_name: Mapped[str] = mapped_column(String(255), nullable=True)
    author_email: Mapped[str] = mapped_column(String(255), nullable=True)
    committed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class PullRequest(Base):
    __tablename__ = "pull_requests"
    __table_args__ = (
        UniqueConstraint("repository_id", "github_pr_number", name="uq_pull_requests_repo_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), nullable=False)
    github_pr_number: Mapped[int] = mapped_column(Integer, nullable=False)
    head_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    base_sha: Mapped[str] = mapped_column(String(64), nullable=True)
    base_branch: Mapped[str] = mapped_column(String(255), nullable=True)
    head_branch: Mapped[str] = mapped_column(String(255), nullable=True)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), nullable=False)
    commit_id: Mapped[int] = mapped_column(ForeignKey("commits.id"), nullable=False)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    uploader: Mapped[str] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class CoverageReportRow(Base):
    __tablename__ = "coverage_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), nullable=False)
    commit_id: Mapped[int] = mapped_column(ForeignKey("commits.id"), nullable=False)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id"), nullable=False)
    line_rate: Mapped[float] = mapped_column(Float, nullable=False)
    branch_rate: Mapped[float] = mapped_column(Float, nullable=True)
    covered_lines: Mapped[int] = mapped_column(Integer, nullable=False)
    total_lines: Mapped[int] = mapped_column(Integer, nullable=False)
    covered_branches: Mapped[int] = mapped_column(Integer, nullable=True)
    total_branches: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    files: Mapped[list["FileCoverage"]] = relationship(cascade="all, delete-orphan")


class FileCoverage(Base):
    __tablename__ = "file_coverages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("coverage_reports.id"), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    line_rate: Mapped[float] = mapped_column(Float, nullable=False)
    branch_rate: Mapped[float] = mapped_column(Float, nullable=True)
    covered_lines: Mapped[int] = mapped_column(Integer, nullable=False)
    total_lines: Mapped[int] = mapped_column(Integer, nullable=False)
    lines: Mapped[list["LineCoverage"]] = relationship(cascade="all, delete-orphan")


class LineCoverage(Base):
    __tablename__ = "line_coverages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_coverage_id: Mapped[int] = mapped_column(ForeignKey("file_coverages.id"), nullable=False)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    hits: Mapped[int] = mapped_column(Integer, nullable=False)
    branch: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    condition_coverage: Mapped[str] = mapped_column(String(255), nullable=True)


class PrAnnotation(Base):
    __tablename__ = "pr_annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pull_request_id: Mapped[int] = mapped_column(ForeignKey("pull_requests.id"), nullable=False)
    report_id: Mapped[int] = mapped_column(ForeignKey("coverage_reports.id"), nullable=False)
    patch_covered_lines: Mapped[int] = mapped_column(Integer, nullable=False)
    patch_total_lines: Mapped[int] = mapped_column(Integer, nullable=False)
    patch_line_rate: Mapped[float] = mapped_column(Float, nullable=False)
    github_comment_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    github_check_run_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class PrFileAnnotation(Base):
    __tablename__ = "pr_file_annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    annotation_id: Mapped[int] = mapped_column(ForeignKey("pr_annotations.id"), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    patch_covered_lines: Mapped[int] = mapped_column(Integer, nullable=False)
    patch_total_lines: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    @property
    def patch_line_rate(self) -> float:
        if self.patch_total_lines == 0:
            return 1.0
        return self.patch_covered_lines / self.patch_total_lines


class PrFileLineAnnotation(Base):
    __tablename__ = "pr_file_line_annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_annotation_id: Mapped[int] = mapped_column(
        ForeignKey("pr_file_annotations.id"), nullable=False
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    covered: Mapped[bool] = mapped_column(Boolean, nullable=False)
    line_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    run_after: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    locked_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    locked_by: Mapped[str] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)
