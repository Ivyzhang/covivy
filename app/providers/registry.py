from __future__ import annotations

from app.config import get_settings
from app.providers.base import CodeHostProvider
from app.providers.github import GitHubProvider
from app.providers.gitlab import GitLabProvider

_provider_overrides: dict[str, CodeHostProvider] = {}


def provider_keys() -> list[str]:
    return ["github", "gitlab"]


def set_provider_override(key: str, provider: CodeHostProvider) -> None:
    _provider_overrides[key] = provider


def reset_provider_overrides() -> None:
    _provider_overrides.clear()


def get_provider(key: str) -> CodeHostProvider:
    if key in _provider_overrides:
        return _provider_overrides[key]
    settings = get_settings()
    if key == "github":
        return GitHubProvider(
            client_id=settings.github_oauth_client_id,
            client_secret=settings.github_oauth_client_secret,
        )
    if key == "gitlab":
        return GitLabProvider(
            client_id=settings.gitlab_oauth_client_id,
            client_secret=settings.gitlab_oauth_client_secret,
            base_url=settings.gitlab_base_url,
        )
    raise KeyError("unknown provider: %s" % key)
