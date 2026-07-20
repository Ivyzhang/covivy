import json
import unittest

import httpx

from app.providers.base import OAuthTokenRefreshError
from app.providers.github import GitHubProvider
from app.providers.gitlab import GitLabProvider
from app.providers.registry import get_provider, provider_keys, reset_provider_overrides


class ProviderRegistryTests(unittest.TestCase):
    def tearDown(self):
        reset_provider_overrides()

    def test_registry_exposes_github_and_gitlab(self):
        self.assertEqual(provider_keys(), ["github", "gitlab"])
        self.assertEqual(get_provider("github").key, "github")
        self.assertEqual(get_provider("gitlab").key, "gitlab")


class GitLabProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_access_token(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "access_token": "gl_rotated",
                    "refresh_token": "gl_refresh_rotated",
                    "expires_in": 7200,
                    "scope": "api read_user",
                },
            )

        provider = GitLabProvider(
            client_id="client",
            client_secret="secret",
            base_url="https://gitlab.example",
            transport=httpx.MockTransport(handler),
        )

        token = await provider.refresh_access_token("gl_refresh")

        self.assertEqual(token.access_token, "gl_rotated")
        self.assertEqual(token.refresh_token, "gl_refresh_rotated")
        self.assertEqual(requests[0].url.path, "/oauth/token")
        self.assertIn(b"grant_type=refresh_token", requests[0].content)
        self.assertIn(b"refresh_token=gl_refresh", requests[0].content)

    async def test_gitlab_oauth_repo_diff_status_and_comment_requests(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.url.path == "/oauth/token":
                return httpx.Response(
                    200,
                    json={
                        "access_token": "gl_access",
                        "refresh_token": "gl_refresh",
                        "expires_in": 3600,
                        "scope": "api read_user",
                    },
                )
            if request.url.path == "/api/v4/user":
                return httpx.Response(200, json={"id": 7, "username": "ivy", "name": "Ivy"})
            if request.url.path == "/api/v4/projects":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": 100,
                            "path_with_namespace": "ivy/demo",
                            "default_branch": "main",
                            "visibility": "private",
                        }
                    ],
                )
            if request.url.raw_path == b"/api/v4/projects/ivy%2Fdemo/merge_requests/5/changes":
                return httpx.Response(
                    200,
                    json={
                        "changes": [
                            {
                                "new_path": "src/app.ts",
                                "diff": "@@ -1,0 +1 @@\n+export const ok = true;\n",
                            }
                        ]
                    },
                )
            if request.url.raw_path == b"/api/v4/projects/ivy%2Fdemo/statuses/abc123":
                return httpx.Response(201, json={"status": "success"})
            if request.url.raw_path == b"/api/v4/projects/ivy%2Fdemo/merge_requests/5/notes":
                return httpx.Response(201, json={"id": 99})
            return httpx.Response(404, json={"message": str(request.url)})

        provider = GitLabProvider(
            client_id="client",
            client_secret="secret",
            base_url="https://gitlab.example",
            transport=httpx.MockTransport(handler),
        )

        token = await provider.exchange_code("code", "https://covivy.example/auth/gitlab/callback")
        user = await provider.current_user(token.access_token)
        repos = await provider.list_repositories(token.access_token)
        files = await provider.merge_request_files(token.access_token, "ivy/demo", 5)
        await provider.create_status(
            token.access_token,
            "ivy/demo",
            "abc123",
            "success",
            "Coverage passed",
            "https://covivy.example/report",
            "covivy/patch",
        )
        note_id = await provider.upsert_merge_request_comment(
            token.access_token,
            "ivy/demo",
            5,
            "<!-- coverage-service:pr-comment -->\nCoverage",
        )

        self.assertEqual(user.login, "ivy")
        self.assertEqual(repos[0].full_name, "ivy/demo")
        self.assertFalse(repos[0].private is False)
        self.assertEqual(files[0].filename, "src/app.ts")
        self.assertEqual(note_id, 99)
        self.assertEqual(requests[0].url.path, "/oauth/token")
        self.assertIn("state=", provider.authorization_url("state", "https://callback"))


class GitHubProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_access_token_rejects_oauth_error_payload(self):
        def handler(request):
            return httpx.Response(
                200,
                json={
                    "error": "bad_refresh_token",
                    "error_description": "The refresh token is invalid.",
                },
            )

        provider = GitHubProvider(
            client_id="client",
            client_secret="secret",
            transport=httpx.MockTransport(handler),
        )

        with self.assertRaises(OAuthTokenRefreshError):
            await provider.refresh_access_token("expired_refresh")

    async def test_refresh_access_token(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "access_token": "gh_rotated",
                    "refresh_token": "gh_refresh_rotated",
                    "expires_in": 28800,
                    "scope": "read:user repo",
                },
            )

        provider = GitHubProvider(
            client_id="client",
            client_secret="secret",
            transport=httpx.MockTransport(handler),
        )

        token = await provider.refresh_access_token("gh_refresh")

        self.assertEqual(token.access_token, "gh_rotated")
        self.assertEqual(token.refresh_token, "gh_refresh_rotated")
        self.assertEqual(requests[0].url.path, "/login/oauth/access_token")
        payload = json.loads(requests[0].content)
        self.assertEqual(payload["grant_type"], "refresh_token")
        self.assertEqual(payload["refresh_token"], "gh_refresh")


if __name__ == "__main__":
    unittest.main()
