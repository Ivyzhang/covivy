import asyncio
import base64
import unittest
from unittest.mock import patch

import httpx

from app.github import InstallationGitHubClient


class FakeResponse:
    def __init__(self, payload, links=None, status_code=200, url="https://api.github.com/test"):
        self._payload = payload
        self.links = links or {}
        self.status_code = status_code
        self.request = httpx.Request("GET", url)

    def raise_for_status(self):
        if self.status_code >= 400:
            response = httpx.Response(self.status_code, request=self.request, json=self._payload)
            raise httpx.HTTPStatusError(
                "Client error '%s' for url '%s'" % (self.status_code, self.request.url),
                request=self.request,
                response=response,
            )
        return None

    def json(self):
        return self._payload


class FakeAsyncClient:
    queued_responses = []
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url, headers=None, params=None):
        self.calls.append(("GET", url, params))
        return self.queued_responses.pop(0)

    async def post(self, url, headers=None, json=None):
        self.calls.append(("POST", url, json))
        return self.queued_responses.pop(0)

    async def patch(self, url, headers=None, json=None):
        self.calls.append(("PATCH", url, json))
        return self.queued_responses.pop(0)


class GitHubClientTests(unittest.TestCase):
    def setUp(self):
        FakeAsyncClient.queued_responses = []
        FakeAsyncClient.calls = []

    def test_pull_files_follows_github_pagination(self):
        FakeAsyncClient.queued_responses = [
            FakeResponse(
                [{"filename": "a.py", "patch": "@@ -1 +1 @@\n+a"}],
                links={"next": {"url": "https://api.github.com/page/2"}},
            ),
            FakeResponse([{"filename": "b.py", "patch": "@@ -2 +2 @@\n+b"}]),
        ]

        with patch("app.github.httpx.AsyncClient", FakeAsyncClient):
            files = asyncio.run(InstallationGitHubClient("token").pull_files("octo", "demo", 7))

        self.assertEqual([item.filename for item in files], ["a.py", "b.py"])
        self.assertEqual(FakeAsyncClient.calls[0][2], {"per_page": 100})
        self.assertEqual(FakeAsyncClient.calls[1][1], "https://api.github.com/page/2")

    def test_file_content_decodes_base64_blob_at_ref(self):
        FakeAsyncClient.queued_responses = [
            FakeResponse(
                {
                    "encoding": "base64",
                    "content": base64.b64encode(b"print('ok')\n").decode("ascii"),
                }
            )
        ]

        with patch("app.github.httpx.AsyncClient", FakeAsyncClient):
            content = asyncio.run(
                InstallationGitHubClient("token").file_content(
                    "octo", "demo", "src/api.py", "abc123"
                )
            )

        self.assertEqual(content, "print('ok')\n")
        self.assertEqual(
            FakeAsyncClient.calls[0],
            (
                "GET",
                "https://api.github.com/repos/octo/demo/contents/src/api.py",
                {"ref": "abc123"},
            ),
        )

    def test_upsert_pr_comment_reuses_marker_found_on_second_page(self):
        FakeAsyncClient.queued_responses = [
            FakeResponse(
                [{"id": 1, "body": "other"}],
                links={"next": {"url": "https://api.github.com/comments?page=2"}},
            ),
            FakeResponse([{"id": 2, "body": "<!-- coverage-service:pr-comment -->\nold"}]),
            FakeResponse({"id": 2}),
        ]

        with patch("app.github.httpx.AsyncClient", FakeAsyncClient):
            comment_id = asyncio.run(
                InstallationGitHubClient("token").upsert_pr_comment(
                    "octo", "demo", 7, "new body"
                )
            )

        self.assertEqual(comment_id, 2)
        self.assertEqual(FakeAsyncClient.calls[-1][0], "PATCH")
        self.assertIn("/issues/comments/2", FakeAsyncClient.calls[-1][1])

    def test_upsert_pr_comment_explains_required_comment_permissions(self):
        FakeAsyncClient.queued_responses = [
            FakeResponse([]),
            FakeResponse(
                {"message": "Resource not accessible by integration"},
                status_code=403,
                url="https://api.github.com/repos/octo/demo/issues/7/comments",
            ),
        ]

        with patch("app.github.httpx.AsyncClient", FakeAsyncClient):
            with self.assertRaisesRegex(RuntimeError, "Pull requests: Read and write"):
                asyncio.run(
                    InstallationGitHubClient("token").upsert_pr_comment(
                        "octo", "demo", 7, "new body"
                    )
                )


if __name__ == "__main__":
    unittest.main()
