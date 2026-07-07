from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import quote

import httpx
import jwt

from app.coverage import parse_unified_diff_changed_line_contents, parse_unified_diff_changed_lines


class GitHubPermissionError(RuntimeError):
    pass


@dataclass(frozen=True)
class PullFilePatch:
    filename: str
    patch: str


class GitHubClient:
    def __init__(self, app_id: str, private_key: str) -> None:
        self.app_id = app_id
        self.private_key = private_key

    def _jwt(self) -> str:
        now = int(time.time())
        return jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": self.app_id},
            self.private_key,
            algorithm="RS256",
        )

    async def installation_token(self, installation_id: int) -> str:
        headers = {
            "Authorization": "Bearer %s" % self._jwt(),
            "Accept": "application/vnd.github+json",
        }
        url = "https://api.github.com/app/installations/%s/access_tokens" % installation_id
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, headers=headers)
            response.raise_for_status()
            return response.json()["token"]


class InstallationGitHubClient:
    def __init__(self, token: str) -> None:
        self.token = token

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": "Bearer %s" % self.token,
            "Accept": "application/vnd.github+json",
        }

    async def _get_paginated(self, url: str, params: Optional[Dict] = None) -> List[Dict]:
        items: List[Dict] = []
        next_url: Optional[str] = url
        next_params = params
        async with httpx.AsyncClient(timeout=30) as client:
            while next_url:
                response = await client.get(next_url, headers=self.headers, params=next_params)
                response.raise_for_status()
                items.extend(response.json())
                next_url = response.links.get("next", {}).get("url")
                next_params = None
        return items

    async def pull_files(self, owner: str, repo: str, number: int) -> List[PullFilePatch]:
        url = "https://api.github.com/repos/%s/%s/pulls/%s/files" % (owner, repo, number)
        return [
            PullFilePatch(filename=item["filename"], patch=item.get("patch") or "")
            for item in await self._get_paginated(url, params={"per_page": 100})
        ]

    async def pull_request(self, owner: str, repo: str, number: int) -> Dict:
        url = "https://api.github.com/repos/%s/%s/pulls/%s" % (owner, repo, number)
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()

    async def file_content(
        self, owner: str, repo: str, path: str, ref: str
    ) -> Optional[str]:
        encoded_path = quote(path)
        url = "https://api.github.com/repos/%s/%s/contents/%s" % (
            owner,
            repo,
            encoded_path,
        )
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=self.headers, params={"ref": ref})
            if response.status_code == 404:
                return None
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            return None
        if payload.get("encoding") != "base64":
            return None
        content = payload.get("content")
        if not isinstance(content, str):
            return None
        return base64.b64decode(content).decode("utf-8", errors="replace")

    async def create_status(
        self,
        owner: str,
        repo: str,
        sha: str,
        state: str,
        description: str,
        target_url: str,
        context: str = "coverage/patch",
    ) -> None:
        url = "https://api.github.com/repos/%s/%s/statuses/%s" % (owner, repo, sha)
        payload = {
            "state": state,
            "context": context,
            "description": description[:140],
            "target_url": target_url,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, headers=self.headers, json=payload)
            response.raise_for_status()

    async def upsert_pr_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        comment_id: Optional[int] = None,
    ) -> int:
        async with httpx.AsyncClient(timeout=20) as client:
            resolved_comment_id = comment_id
            if resolved_comment_id is None:
                comments_url = "https://api.github.com/repos/%s/%s/issues/%s/comments" % (
                    owner,
                    repo,
                    pr_number,
                )
                for item in await self._get_paginated(comments_url, params={"per_page": 100}):
                    if "<!-- coverage-service:pr-comment -->" in (item.get("body") or ""):
                        resolved_comment_id = int(item["id"])
                        break
            if resolved_comment_id:
                url = "https://api.github.com/repos/%s/%s/issues/comments/%s" % (
                    owner,
                    repo,
                    resolved_comment_id,
                )
                response = await client.patch(url, headers=self.headers, json={"body": body})
            else:
                url = "https://api.github.com/repos/%s/%s/issues/%s/comments" % (
                    owner,
                    repo,
                    pr_number,
                )
                response = await client.post(url, headers=self.headers, json={"body": body})
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 403:
                    raise GitHubPermissionError(
                        "GitHub App cannot write PR comments for %s/%s#%s. "
                        "Enable repository Issues, set repository permission Issues: Read and "
                        "write or Pull requests: Read and write, then approve the updated "
                        "installation."
                        % (owner, repo, pr_number)
                    ) from exc
                raise
            return int(response.json()["id"])


def changed_lines_from_pull_files(files: List[PullFilePatch]) -> Dict[str, set]:
    return {
        file.filename: parse_unified_diff_changed_lines(file.patch)
        for file in files
        if file.patch
    }


def changed_line_contents_from_pull_files(files: List[PullFilePatch]) -> Dict[str, Dict[int, str]]:
    return {
        file.filename: parse_unified_diff_changed_line_contents(file.patch)
        for file in files
        if file.patch
    }
