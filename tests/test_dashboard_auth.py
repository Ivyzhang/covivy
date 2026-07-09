import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db import Base, get_session
from app.main import app
from app.models import (
    Account,
    ExternalIdentity,
    Installation,
    OAuthToken,
    Repository,
    RepositorySettings,
    UserSession,
    DashboardUser,
)
from app.providers.base import OAuthTokenResult, ProviderRepository, ProviderUser
from app.providers.registry import reset_provider_overrides, set_provider_override


class FakeDashboardProvider:
    key = "github"

    def __init__(self):
        self.rotated = False

    def authorization_url(self, state, redirect_uri):
        return "https://github.example/login?state=%s&redirect_uri=%s" % (state, redirect_uri)

    async def exchange_code(self, code, redirect_uri):
        self.last_code = code
        return OAuthTokenResult(
            access_token="gho_access",
            refresh_token="ghr_refresh",
            expires_at=None,
            scope="repo,user:email",
        )

    async def current_user(self, access_token):
        return ProviderUser(provider="github", external_id="42", login="ivy", name="Ivy")

    async def list_repositories(self, access_token):
        return [
            ProviderRepository(
                provider="github",
                external_id="100",
                owner="ivy",
                name="demo",
                full_name="ivy/demo",
                default_branch="main",
                private=False,
            )
        ]


class DashboardAuthTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.settings = Settings(
            database_url="sqlite+pysqlite:///:memory:",
            public_base_url="http://covivy.example",
            upload_token_pepper="pepper",
            github_oauth_client_id="github-client",
            github_oauth_client_secret="github-secret",
            gitlab_oauth_client_id="gitlab-client",
            gitlab_oauth_client_secret="gitlab-secret",
            dashboard_session_secret="session-secret",
            github_app_install_url="https://github.com/apps/covivy/installations/new",
        )

        def override_session():
            session = self.Session()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_settings] = lambda: self.settings
        reset_provider_overrides()
        self.provider = FakeDashboardProvider()
        set_provider_override("github", self.provider)
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        reset_provider_overrides()

    def login(self):
        start = self.client.get("/auth/github", follow_redirects=False)
        self.assertEqual(start.status_code, 307)
        location = start.headers["location"]
        state = location.split("state=", 1)[1].split("&", 1)[0]
        return self.client.get("/auth/github/callback?code=abc&state=%s" % state)

    def test_github_oauth_callback_creates_session_identity_and_token(self):
        response = self.login()

        self.assertEqual(response.status_code, 200)
        self.assertIn("app-shell", response.text)
        self.assertIn("Covivy", response.text)
        with self.Session() as session:
            identity = session.scalar(select(ExternalIdentity))
            token = session.scalar(select(OAuthToken))
            user_session = session.scalar(select(UserSession))

        self.assertEqual(identity.provider, "github")
        self.assertEqual(identity.external_id, "42")
        self.assertEqual(identity.login, "ivy")
        self.assertEqual(token.access_token, "gho_access")
        self.assertIsNotNone(user_session.session_token_hash)
        self.assertIn("covivy_session", response.headers.get("set-cookie", ""))

    def test_oauth_callback_rejects_invalid_state(self):
        response = self.client.get("/auth/github/callback?code=abc&state=wrong")

        self.assertEqual(response.status_code, 400)

    def test_dashboard_does_not_link_unconfigured_oauth_provider(self):
        self.settings = Settings(
            database_url="sqlite+pysqlite:///:memory:",
            public_base_url="http://covivy.example",
            upload_token_pepper="pepper",
            dashboard_session_secret="session-secret",
            github_oauth_client_id="",
            github_oauth_client_secret="",
            gitlab_oauth_client_id="",
            gitlab_oauth_client_secret="",
        )

        response = self.client.get("/dashboard")
        auth_response = self.client.get("/auth/github", follow_redirects=False)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('href="/auth/github"', response.text)
        self.assertNotIn('href="/auth/gitlab"', response.text)
        self.assertIn("GitHub unavailable", response.text)
        self.assertIn("GitLab unavailable", response.text)
        self.assertEqual(auth_response.status_code, 400)
        self.assertEqual(auth_response.json()["detail"], "GitHub OAuth is not configured")

    def test_dashboard_shows_gitlab_as_disabled_when_only_github_is_configured(self):
        self.settings = Settings(
            database_url="sqlite+pysqlite:///:memory:",
            public_base_url="http://covivy.example",
            upload_token_pepper="pepper",
            github_oauth_client_id="github-client",
            github_oauth_client_secret="github-secret",
            gitlab_oauth_client_id="",
            gitlab_oauth_client_secret="",
            dashboard_session_secret="session-secret",
        )

        response = self.client.get("/dashboard")
        gitlab_response = self.client.get("/auth/gitlab", follow_redirects=False)

        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/auth/github"', response.text)
        self.assertIn("GitLab unavailable", response.text)
        self.assertIn("disabled", response.text)
        self.assertNotIn('href="/auth/gitlab"', response.text)
        self.assertEqual(gitlab_response.status_code, 400)
        self.assertEqual(gitlab_response.json()["detail"], "GitLab OAuth is not configured")

    def test_homepage_renders_marketing_login_and_registration_ui(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Covivy", response.text)
        self.assertIn("Log in to your account", response.text)
        self.assertIn("Sign in with GitHub", response.text)
        self.assertIn("Register instead", response.text)
        self.assertIn("Coverage intelligence for modern PR workflows", response.text)
        self.assertIn('name="email"', response.text)
        self.assertIn('name="password"', response.text)

    def test_local_registration_creates_user_and_session_then_login_works(self):
        register_response = self.client.post(
            "/register",
            data={
                "email": "ivy@example.com",
                "password": "secret123",
                "display_name": "Ivy",
            },
        )

        self.assertEqual(register_response.status_code, 200)
        self.assertIn("app-shell", register_response.text)
        self.assertIn("Covivy", register_response.text)
        self.assertIn("covivy_session", register_response.headers.get("set-cookie", ""))
        with self.Session() as session:
            user = session.scalar(select(DashboardUser))
        self.assertEqual(user.email, "ivy@example.com")
        self.assertNotEqual(user.password_hash, "secret123")

        self.client.cookies.clear()
        login_response = self.client.post(
            "/login",
            data={"email": "ivy@example.com", "password": "secret123"},
        )

        self.assertEqual(login_response.status_code, 200)
        self.assertIn("app-shell", login_response.text)
        self.assertIn("Covivy", login_response.text)
        self.assertIn("covivy_session", login_response.headers.get("set-cookie", ""))

    def test_authenticated_dashboard_shows_logout_and_logout_clears_session(self):
        self.client.post(
            "/register",
            data={
                "email": "ivy@example.com",
                "password": "secret123",
                "display_name": "Ivy",
            },
        )

        dashboard_response = self.client.get("/dashboard")
        logout_response = self.client.post("/logout", follow_redirects=False)

        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn("Logout", dashboard_response.text)
        self.assertIn("app-shell", dashboard_response.text)
        self.assertIn("dashboard-card", dashboard_response.text)
        self.assertIn("Covivy", dashboard_response.text)
        self.assertNotIn("GitHub login", dashboard_response.text)
        self.assertNotIn("GitLab login", dashboard_response.text)
        self.assertEqual(logout_response.status_code, 303)
        self.assertEqual(logout_response.headers["location"], "/")
        self.assertIn("covivy_session=", logout_response.headers.get("set-cookie", ""))
        self.assertIn("Max-Age=0", logout_response.headers.get("set-cookie", ""))

    def test_local_login_rejects_invalid_password(self):
        self.client.post(
            "/register",
            data={
                "email": "ivy@example.com",
                "password": "secret123",
                "display_name": "Ivy",
            },
        )
        self.client.cookies.clear()

        response = self.client.post(
            "/login",
            data={"email": "ivy@example.com", "password": "wrong"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "invalid email or password")

    def test_dashboard_lists_provider_repositories_and_onboards_settings(self):
        self.login()

        response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertIn("ivy/demo", response.text)
        self.assertIn("Install GitHub App", response.text)

        onboard_response = self.client.post(
            "/dashboard/onboard",
            data={
                "provider": "github",
                "provider_repo_id": "100",
                "full_name": "ivy/demo",
                "default_branch": "main",
                "private": "false",
            },
        )

        self.assertEqual(onboard_response.status_code, 200)
        self.assertIn("Waiting for GitHub App installation", onboard_response.text)
        with self.Session() as session:
            repository = session.scalar(select(Repository))
            settings = session.scalar(select(RepositorySettings))

        self.assertEqual(repository.provider, "github")
        self.assertEqual(repository.provider_repo_id, "100")
        self.assertEqual(settings.patch_coverage_target, 0.8)
        self.assertTrue(settings.status_enabled)
        self.assertTrue(settings.comment_enabled)

    def test_dashboard_marks_github_app_installed_repository_configured(self):
        self.login()
        with self.Session() as session:
            account = Account(github_user_id=42, login="ivy")
            session.add(account)
            session.flush()
            installation = Installation(github_installation_id=999, account_id=account.id)
            session.add(installation)
            session.flush()
            session.add(
                Repository(
                    installation_id=installation.id,
                    github_repo_id=100,
                    provider="github",
                    provider_repo_id="100",
                    owner="ivy",
                    name="demo",
                    full_name="ivy/demo",
                    default_branch="main",
                    private=False,
                )
            )
            session.commit()

        response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Configured", response.text)
        self.assertIn("/dashboard/repos/", response.text)
        self.assertNotIn("Install GitHub App", response.text)

    def test_onboarding_reuses_existing_github_repository_from_webhook(self):
        with self.Session() as session:
            session.add(
                Repository(
                    owner="ivy",
                    name="demo",
                    full_name="ivy/demo",
                    default_branch="main",
                    private=False,
                )
            )
            session.commit()
        self.login()

        response = self.client.post(
            "/dashboard/onboard",
            data={
                "provider": "github",
                "provider_repo_id": "100",
                "full_name": "ivy/demo",
                "default_branch": "main",
                "private": "false",
            },
        )

        self.assertEqual(response.status_code, 200)
        with self.Session() as session:
            repositories = session.scalars(select(Repository)).all()
            settings = session.scalar(select(RepositorySettings))

        self.assertEqual(len(repositories), 1)
        self.assertEqual(repositories[0].provider_repo_id, "100")
        self.assertIsNotNone(settings)

    def test_settings_page_updates_targets_ignores_and_toggles_then_rotates_token(self):
        self.login()
        self.client.post(
            "/dashboard/onboard",
            data={
                "provider": "github",
                "provider_repo_id": "100",
                "full_name": "ivy/demo",
                "default_branch": "main",
                "private": "false",
            },
        )
        with self.Session() as session:
            repository = session.scalar(select(Repository))
            repo_id = repository.id

        update_response = self.client.post(
            "/dashboard/repos/%s/settings" % repo_id,
            data={
                "patch_coverage_target": "0.9",
                "project_coverage_target": "0.85",
                "ignore_paths": "tests/**\ndocs/**",
                "status_enabled": "on",
            },
        )

        self.assertEqual(update_response.status_code, 200)
        with self.Session() as session:
            saved = session.scalar(select(RepositorySettings))
        self.assertEqual(saved.patch_coverage_target, 0.9)
        self.assertEqual(saved.project_coverage_target, 0.85)
        self.assertEqual(saved.ignore_paths, ["tests/**", "docs/**"])
        self.assertTrue(saved.status_enabled)
        self.assertFalse(saved.comment_enabled)

        rotate_response = self.client.post("/dashboard/repos/%s/rotate-token" % repo_id)

        self.assertEqual(rotate_response.status_code, 200)
        self.assertIn("cov_", rotate_response.text)


if __name__ == "__main__":
    unittest.main()
