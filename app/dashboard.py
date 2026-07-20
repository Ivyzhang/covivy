from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    DashboardUser,
    ExternalIdentity,
    OAuthToken,
    Repository,
    RepositorySettings,
    UserSession,
)
from app.providers.base import CodeHostProvider, OAuthTokenResult, ProviderRepository, ProviderUser
from app.security import generate_upload_token, hash_upload_token

SESSION_COOKIE = "covivy_session"


def session_hash(token: str, settings: Settings) -> str:
    return hash_upload_token(token, settings.dashboard_session_secret)


def create_dashboard_session(
    session: Session,
    settings: Settings,
    identity: ExternalIdentity,
    *,
    now: Optional[datetime] = None,
) -> str:
    raw_token = "sess_" + secrets.token_urlsafe(32)
    created_at = now or datetime.utcnow()
    session.add(
        UserSession(
            identity_id=identity.id,
            session_token_hash=session_hash(raw_token, settings),
            expires_at=created_at + timedelta(days=30),
        )
    )
    return raw_token


def create_dashboard_user_session(
    session: Session,
    settings: Settings,
    user: DashboardUser,
    *,
    now: Optional[datetime] = None,
) -> str:
    raw_token = "sess_" + secrets.token_urlsafe(32)
    created_at = now or datetime.utcnow()
    session.add(
        UserSession(
            dashboard_user_id=user.id,
            session_token_hash=session_hash(raw_token, settings),
            expires_at=created_at + timedelta(days=30),
        )
    )
    return raw_token


def current_identity_from_session(
    session: Session, settings: Settings, raw_session_token: Optional[str]
) -> Optional[ExternalIdentity]:
    if not raw_session_token:
        return None
    row = session.scalar(
        select(UserSession).where(
            UserSession.session_token_hash == session_hash(raw_session_token, settings),
            UserSession.expires_at > datetime.utcnow(),
        )
    )
    if row is None:
        return None
    return session.get(ExternalIdentity, row.identity_id)


def require_identity(
    session: Session, settings: Settings, raw_session_token: Optional[str]
) -> ExternalIdentity:
    identity = current_identity_from_session(session, settings, raw_session_token)
    if identity is None:
        raise PermissionError("dashboard login required")
    return identity


def current_session_row(
    session: Session, settings: Settings, raw_session_token: Optional[str]
) -> Optional[UserSession]:
    if not raw_session_token:
        return None
    return session.scalar(
        select(UserSession).where(
            UserSession.session_token_hash == session_hash(raw_session_token, settings),
            UserSession.expires_at > datetime.utcnow(),
        )
    )


def current_actor_label(
    session: Session, settings: Settings, raw_session_token: Optional[str]
) -> Optional[str]:
    row = current_session_row(session, settings, raw_session_token)
    if row is None:
        return None
    if row.identity_id:
        identity = session.get(ExternalIdentity, row.identity_id)
        return identity.login if identity else None
    if row.dashboard_user_id:
        user = session.get(DashboardUser, row.dashboard_user_id)
        return user.display_name or user.email if user else None
    return None


def require_dashboard_session(
    session: Session, settings: Settings, raw_session_token: Optional[str]
) -> UserSession:
    row = current_session_row(session, settings, raw_session_token)
    if row is None:
        raise PermissionError("dashboard login required")
    return row


def password_hash(password: str, settings: Settings) -> str:
    return hash_upload_token(password, settings.dashboard_session_secret)


def verify_password(password: str, settings: Settings, expected_hash: str) -> bool:
    return secrets.compare_digest(password_hash(password, settings), expected_hash)


def create_dashboard_user(
    session: Session,
    settings: Settings,
    email: str,
    password: str,
    display_name: Optional[str],
) -> DashboardUser:
    normalized_email = email.strip().lower()
    if not normalized_email:
        raise ValueError("email is required")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    existing = session.scalar(select(DashboardUser).where(DashboardUser.email == normalized_email))
    if existing is not None:
        raise ValueError("email is already registered")
    user = DashboardUser(
        email=normalized_email,
        display_name=(display_name or "").strip() or None,
        password_hash=password_hash(password, settings),
    )
    session.add(user)
    session.flush()
    return user


def authenticate_dashboard_user(
    session: Session, settings: Settings, email: str, password: str
) -> Optional[DashboardUser]:
    user = session.scalar(select(DashboardUser).where(DashboardUser.email == email.strip().lower()))
    if user is None:
        return None
    if not verify_password(password, settings, user.password_hash):
        return None
    return user


def upsert_identity_and_token(
    session: Session,
    user: ProviderUser,
    token: OAuthTokenResult,
) -> ExternalIdentity:
    identity = session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == user.provider,
            ExternalIdentity.external_id == user.external_id,
        )
    )
    if identity is None:
        identity = ExternalIdentity(
            provider=user.provider,
            external_id=user.external_id,
            login=user.login,
            name=user.name,
        )
        session.add(identity)
        session.flush()
    identity.login = user.login
    identity.name = user.name

    oauth_token = session.scalar(select(OAuthToken).where(OAuthToken.identity_id == identity.id))
    if oauth_token is None:
        oauth_token = OAuthToken(identity_id=identity.id, access_token=token.access_token)
        session.add(oauth_token)
    oauth_token.access_token = token.access_token
    oauth_token.refresh_token = token.refresh_token
    oauth_token.expires_at = token.expires_at
    oauth_token.scope = token.scope
    return identity


def token_for_identity(
    session: Session, identity: ExternalIdentity, *, for_update: bool = False
) -> OAuthToken:
    statement = select(OAuthToken).where(OAuthToken.identity_id == identity.id)
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    token = session.scalar(statement)
    if token is None:
        raise PermissionError("OAuth token missing")
    return token


async def refresh_token_for_identity(
    session: Session,
    identity: ExternalIdentity,
    provider: CodeHostProvider,
    *,
    force: bool = False,
    failed_access_token: Optional[str] = None,
) -> OAuthToken:
    token = token_for_identity(session, identity)
    refresh_at = datetime.utcnow() + timedelta(minutes=1)
    if not force and (token.expires_at is None or token.expires_at > refresh_at):
        return token

    token = token_for_identity(session, identity, for_update=True)
    if force and failed_access_token and token.access_token != failed_access_token:
        return token
    if not force and (token.expires_at is None or token.expires_at > refresh_at):
        return token
    if not token.refresh_token:
        raise PermissionError("OAuth token refresh unavailable")

    refreshed = await provider.refresh_access_token(token.refresh_token)
    token.access_token = refreshed.access_token
    token.refresh_token = refreshed.refresh_token or token.refresh_token
    token.expires_at = refreshed.expires_at
    token.scope = refreshed.scope or token.scope
    session.flush()
    return token


def parse_ignore_paths(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def ensure_repository_settings(
    session: Session, repository: Repository, settings: Settings
) -> RepositorySettings:
    row = session.scalar(
        select(RepositorySettings).where(RepositorySettings.repository_id == repository.id)
    )
    if row is None:
        row = RepositorySettings(
            repository_id=repository.id,
            patch_coverage_target=settings.patch_coverage_minimum,
            project_coverage_target=settings.patch_coverage_minimum,
            ignore_paths=[],
            status_enabled=True,
            comment_enabled=True,
        )
        session.add(row)
    return row


def onboard_repository(
    session: Session,
    settings: Settings,
    provider_repo: ProviderRepository,
) -> tuple[Repository, Optional[str]]:
    repository = session.scalar(
        select(Repository).where(
            Repository.provider == provider_repo.provider,
            Repository.provider_repo_id == provider_repo.external_id,
        )
    )
    if repository is None:
        repository = session.scalar(
            select(Repository).where(
                Repository.owner == provider_repo.owner,
                Repository.name == provider_repo.name,
            )
        )
    raw_token = None
    if repository is None:
        repository = Repository(
            provider=provider_repo.provider,
            provider_repo_id=provider_repo.external_id,
            owner=provider_repo.owner,
            name=provider_repo.name,
            full_name=provider_repo.full_name,
            default_branch=provider_repo.default_branch,
            private=provider_repo.private,
            active=True,
        )
        session.add(repository)
    repository.provider = provider_repo.provider
    repository.provider_repo_id = provider_repo.external_id
    repository.owner = provider_repo.owner
    repository.name = provider_repo.name
    repository.full_name = provider_repo.full_name
    repository.default_branch = provider_repo.default_branch
    repository.private = provider_repo.private
    repository.active = True
    if provider_repo.provider == "github":
        repository.github_repo_id = int(provider_repo.external_id)
    if not repository.upload_token_hash:
        raw_token = generate_upload_token()
        repository.upload_token_hash = hash_upload_token(raw_token, settings.upload_token_pepper)
    session.flush()
    ensure_repository_settings(session, repository, settings)
    return repository, raw_token
