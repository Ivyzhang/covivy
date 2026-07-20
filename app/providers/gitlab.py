from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote, urlencode

import httpx

from app.github import PullFilePatch
from app.providers.base import OAuthTokenResult, ProviderRepository, ProviderUser


class GitLabProvider:
    key = "gitlab"

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        base_url: str = "https://gitlab.com",
        *,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    @property
    def api_url(self) -> str:
        return "%s/api/v4" % self.base_url

    def authorization_url(self, state: str, redirect_uri: str) -> str:
        query = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "api read_user",
                "state": state,
            }
        )
        return "%s/oauth/authorize?%s" % (self.base_url, query)

    async def exchange_code(self, code: str, redirect_uri: str) -> OAuthTokenResult:
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            response = await client.post("%s/oauth/token" % self.base_url, data=payload)
            response.raise_for_status()
        data = response.json()
        expires_at = None
        if data.get("expires_in"):
            expires_at = datetime.utcnow() + timedelta(seconds=int(data["expires_in"]))
        return OAuthTokenResult(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            scope=data.get("scope"),
        )

    async def refresh_access_token(self, refresh_token: str) -> OAuthTokenResult:
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            response = await client.post("%s/oauth/token" % self.base_url, data=payload)
            response.raise_for_status()
        data = response.json()
        expires_at = None
        if data.get("expires_in"):
            expires_at = datetime.utcnow() + timedelta(seconds=int(data["expires_in"]))
        return OAuthTokenResult(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            scope=data.get("scope"),
        )

    def _headers(self, access_token: str) -> dict[str, str]:
        return {"Authorization": "Bearer %s" % access_token}

    def _project(self, full_name: str) -> str:
        return quote(full_name, safe="")

    async def current_user(self, access_token: str) -> ProviderUser:
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            response = await client.get("%s/user" % self.api_url, headers=self._headers(access_token))
            response.raise_for_status()
        data = response.json()
        return ProviderUser(
            provider=self.key,
            external_id=str(data["id"]),
            login=data["username"],
            name=data.get("name"),
        )

    async def list_repositories(self, access_token: str) -> list[ProviderRepository]:
        repos: list[ProviderRepository] = []
        url: Optional[str] = "%s/projects" % self.api_url
        params = {"membership": "true", "per_page": 100, "order_by": "last_activity_at"}
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            while url:
                response = await client.get(url, headers=self._headers(access_token), params=params)
                response.raise_for_status()
                for item in response.json():
                    full_name = item["path_with_namespace"]
                    owner, name = full_name.rsplit("/", 1)
                    repos.append(
                        ProviderRepository(
                            provider=self.key,
                            external_id=str(item["id"]),
                            owner=owner,
                            name=name,
                            full_name=full_name,
                            default_branch=item.get("default_branch") or "main",
                            private=item.get("visibility") != "public",
                        )
                    )
                url = response.links.get("next", {}).get("url")
                params = None
        return repos

    async def merge_request_files(
        self, access_token: str, full_name: str, number: int
    ) -> list[PullFilePatch]:
        url = "%s/projects/%s/merge_requests/%s/changes" % (
            self.api_url,
            self._project(full_name),
            number,
        )
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            response = await client.get(url, headers=self._headers(access_token))
            response.raise_for_status()
        return [
            PullFilePatch(filename=item["new_path"], patch=item.get("diff") or "")
            for item in response.json().get("changes", [])
        ]

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
        gitlab_state = {"failure": "failed", "error": "failed"}.get(state, state)
        url = "%s/projects/%s/statuses/%s" % (self.api_url, self._project(full_name), sha)
        payload = {
            "state": gitlab_state,
            "description": description[:255],
            "target_url": target_url,
            "name": context,
        }
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            response = await client.post(url, headers=self._headers(access_token), json=payload)
            response.raise_for_status()

    async def upsert_merge_request_comment(
        self,
        access_token: str,
        full_name: str,
        number: int,
        body: str,
        comment_id: Optional[int] = None,
    ) -> int:
        headers = self._headers(access_token)
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            if comment_id:
                response = await client.put(
                    "%s/projects/%s/merge_requests/%s/notes/%s"
                    % (self.api_url, self._project(full_name), number, comment_id),
                    headers=headers,
                    json={"body": body},
                )
            else:
                response = await client.post(
                    "%s/projects/%s/merge_requests/%s/notes"
                    % (self.api_url, self._project(full_name), number),
                    headers=headers,
                    json={"body": body},
                )
            response.raise_for_status()
        return int(response.json()["id"])
