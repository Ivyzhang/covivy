from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol

from app.github import PullFilePatch


@dataclass(frozen=True)
class OAuthTokenResult:
    access_token: str
    refresh_token: Optional[str]
    expires_at: Optional[datetime]
    scope: Optional[str]


@dataclass(frozen=True)
class ProviderUser:
    provider: str
    external_id: str
    login: str
    name: Optional[str] = None


@dataclass(frozen=True)
class ProviderRepository:
    provider: str
    external_id: str
    owner: str
    name: str
    full_name: str
    default_branch: str
    private: bool


class CodeHostProvider(Protocol):
    key: str

    def authorization_url(self, state: str, redirect_uri: str) -> str:
        raise NotImplementedError

    async def exchange_code(self, code: str, redirect_uri: str) -> OAuthTokenResult:
        raise NotImplementedError

    async def current_user(self, access_token: str) -> ProviderUser:
        raise NotImplementedError

    async def list_repositories(self, access_token: str) -> list[ProviderRepository]:
        raise NotImplementedError

    async def merge_request_files(
        self, access_token: str, full_name: str, number: int
    ) -> list[PullFilePatch]:
        raise NotImplementedError

    async def create_status(
        self,
        access_token: str,
        full_name: str,
        sha: str,
        state: str,
        description: str,
        target_url: str,
        context: str,
    ) -> None:
        raise NotImplementedError

    async def upsert_merge_request_comment(
        self,
        access_token: str,
        full_name: str,
        number: int,
        body: str,
        comment_id: Optional[int] = None,
    ) -> int:
        raise NotImplementedError
