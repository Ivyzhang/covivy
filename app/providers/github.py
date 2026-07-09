from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import httpx

from app.github import PullFilePatch
from app.providers.base import OAuthTokenResult, ProviderRepository, ProviderUser


class GitHubProvider:
    key = "github"

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        *,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.transport = transport

    @property
    def api_url(self) -> str:
        return "https://api.github.com"

    def authorization_url(self, state: str, redirect_uri: str) -> str:
        query = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": redirect_uri,
                "scope": "read:user repo",
                "state": state,
            }
        )
        return "https://github.com/login/oauth/authorize?%s" % query

    async def exchange_code(self, code: str, redirect_uri: str) -> OAuthTokenResult:
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            response = await client.post(
                "https://github.com/login/oauth/access_token",
                json=payload,
                headers={"Accept": "application/json"},
            )
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
        return {
            "Authorization": "Bearer %s" % access_token,
            "Accept": "application/vnd.github+json",
        }

    async def current_user(self, access_token: str) -> ProviderUser:
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            response = await client.get("%s/user" % self.api_url, headers=self._headers(access_token))
            response.raise_for_status()
        data = response.json()
        return ProviderUser(
            provider=self.key,
            external_id=str(data["id"]),
            login=data["login"],
            name=data.get("name"),
        )

    async def list_repositories(self, access_token: str) -> list[ProviderRepository]:
        repos: list[ProviderRepository] = []
        url: Optional[str] = "%s/user/repos" % self.api_url
        params = {"per_page": 100, "sort": "updated"}
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            while url:
                response = await client.get(url, headers=self._headers(access_token), params=params)
                response.raise_for_status()
                for item in response.json():
                    owner = item["owner"]["login"]
                    repos.append(
                        ProviderRepository(
                            provider=self.key,
                            external_id=str(item["id"]),
                            owner=owner,
                            name=item["name"],
                            full_name=item["full_name"],
                            default_branch=item.get("default_branch") or "main",
                            private=bool(item.get("private")),
                        )
                    )
                url = response.links.get("next", {}).get("url")
                params = None
        return repos

    async def merge_request_files(
        self, access_token: str, full_name: str, number: int
    ) -> list[PullFilePatch]:
        owner, repo = full_name.split("/", 1)
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            response = await client.get(
                "%s/repos/%s/%s/pulls/%s/files" % (self.api_url, owner, repo, number),
                headers=self._headers(access_token),
                params={"per_page": 100},
            )
            response.raise_for_status()
        return [
            PullFilePatch(filename=item["filename"], patch=item.get("patch") or "")
            for item in response.json()
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
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            response = await client.post(
                "%s/repos/%s/statuses/%s" % (self.api_url, full_name, sha),
                headers=self._headers(access_token),
                json={
                    "state": state,
                    "description": description[:140],
                    "target_url": target_url,
                    "context": context,
                },
            )
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
                response = await client.patch(
                    "%s/repos/%s/issues/comments/%s" % (self.api_url, full_name, comment_id),
                    headers=headers,
                    json={"body": body},
                )
            else:
                response = await client.post(
                    "%s/repos/%s/issues/%s/comments" % (self.api_url, full_name, number),
                    headers=headers,
                    json={"body": body},
                )
            response.raise_for_status()
        return int(response.json()["id"])
