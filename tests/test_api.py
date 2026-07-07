import hmac
import json
import tempfile
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import Base
from app.main import app
from app.models import (
    CoverageReportRow,
    FileCoverage,
    Job,
    LineCoverage,
    PrAnnotation,
    PullRequest,
    Repository,
    Upload,
)
from app.security import hash_upload_token, verify_upload_token
from app.services import process_parse_upload_job


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.tmpdir = tempfile.TemporaryDirectory()
        self.settings = Settings(
            database_url="sqlite+pysqlite:///:memory:",
            storage_root=self.tmpdir.name,
            public_base_url="https://coverage.example",
            upload_token_pepper="pepper",
            github_webhook_secret="secret",
            admin_token="admin-secret",
            patch_coverage_minimum=0.8,
        )

        def override_session():
            session = self.Session()
            try:
                yield session
            finally:
                session.close()

        from app.config import get_settings
        from app.db import get_session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_settings] = lambda: self.settings
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.tmpdir.cleanup()

    def sign(self, payload):
        body = json.dumps(payload, separators=(",", ":")).encode()
        digest = hmac.new(b"secret", body, "sha256").hexdigest()
        return body, {"X-Hub-Signature-256": "sha256=" + digest}

    def test_healthz(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_upload_endpoint_authenticates_stores_file_and_enqueues_parse_job(self):
        with self.Session() as session:
            repository = Repository(
                owner="octo",
                name="demo",
                full_name="octo/demo",
                default_branch="main",
                private=False,
                upload_token_hash=hash_upload_token("cov_secret", "pepper"),
            )
            session.add(repository)
            session.commit()

        response = self.client.post(
            "/api/v1/uploads",
            headers={"Authorization": "Bearer cov_secret"},
            data={
                "repository": "octo/demo",
                "commit_sha": "abc123",
                "branch": "feature",
                "parent_sha": "base123",
                "pr_number": "7",
                "format": "lcov",
                "uploader": "test",
            },
            files={"file": ("lcov.info", b"SF:src/api.py\nDA:1,1\nend_of_record\n")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "queued")
        with self.Session() as session:
            job = session.scalar(select(Job).where(Job.type == "parse_upload"))
        self.assertEqual(job.payload_json["pr_number"], 7)

    def test_local_upload_then_worker_parse_loop_persists_commit_coverage(self):
        with self.Session() as session:
            session.add(
                Repository(
                    owner="octo",
                    name="demo",
                    full_name="octo/demo",
                    default_branch="main",
                    private=False,
                    upload_token_hash=hash_upload_token("cov_secret", "pepper"),
                )
            )
            session.commit()

        response = self.client.post(
            "/api/v1/uploads",
            headers={"Authorization": "Bearer cov_secret"},
            data={
                "repository": "octo/demo",
                "commit_sha": "abc123",
                "branch": "main",
                "format": "lcov",
                "uploader": "local",
            },
            files={"file": ("lcov.info", b"SF:src/api.py\nDA:1,1\nDA:2,0\nend_of_record\n")},
        )
        self.assertEqual(response.status_code, 200)

        with self.Session() as session:
            job = session.scalar(select(Job).where(Job.type == "parse_upload"))
            process_parse_upload_job(session, job)
            session.commit()

        response = self.client.get("/api/v1/repos/octo/demo/commits/abc123")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["covered_lines"], 1)
        self.assertEqual(body["total_lines"], 2)
        self.assertEqual(body["files"][0]["path"], "src/api.py")

    def test_rotate_upload_token_endpoint_returns_raw_token_once(self):
        with self.Session() as session:
            session.add(
                Repository(
                    owner="octo",
                    name="demo",
                    full_name="octo/demo",
                    default_branch="main",
                    private=False,
                )
            )
            session.commit()

        response = self.client.post("/api/v1/repos/octo/demo/upload-token")
        self.assertEqual(response.status_code, 401)

        response = self.client.post(
            "/api/v1/repos/octo/demo/upload-token",
            headers={"Authorization": "Bearer admin-secret"},
        )

        self.assertEqual(response.status_code, 200)
        token = response.json()["upload_token"]
        self.assertTrue(token.startswith("cov_"))
        with self.Session() as session:
            repository = session.scalar(select(Repository))
        self.assertTrue(verify_upload_token(token, "pepper", repository.upload_token_hash))

    def test_github_webhook_rejects_bad_signature(self):
        response = self.client.post(
            "/api/v1/github/webhook",
            content=b"{}",
            headers={"X-Hub-Signature-256": "sha256=bad", "X-GitHub-Event": "push"},
        )
        self.assertEqual(response.status_code, 401)

    def test_pull_request_webhook_upserts_pr(self):
        payload = {
            "repository": {
                "id": 300,
                "name": "demo",
                "full_name": "octo/demo",
                "private": False,
                "default_branch": "main",
                "owner": {"login": "octo"},
            },
            "pull_request": {
                "number": 7,
                "head": {"sha": "abc123", "ref": "feature"},
                "base": {"sha": "base123", "ref": "main"},
                "state": "open",
                "title": "Add API",
            },
        }
        body, headers = self.sign(payload)
        headers["X-GitHub-Event"] = "pull_request"

        response = self.client.post("/api/v1/github/webhook", content=body, headers=headers)

        self.assertEqual(response.status_code, 200)
        with self.Session() as session:
            pull = session.scalar(select(PullRequest))
            repo = session.scalar(select(Repository))
        self.assertEqual(repo.full_name, "octo/demo")
        self.assertEqual(pull.github_pr_number, 7)
        self.assertEqual(pull.head_sha, "abc123")

    def test_pull_request_webhook_after_coverage_upload_schedules_github_update(self):
        with self.Session() as session:
            session.add(
                Repository(
                    owner="octo",
                    name="demo",
                    full_name="octo/demo",
                    default_branch="main",
                    private=False,
                    upload_token_hash=hash_upload_token("cov_secret", "pepper"),
                )
            )
            session.commit()

        response = self.client.post(
            "/api/v1/uploads",
            headers={"Authorization": "Bearer cov_secret"},
            data={
                "repository": "octo/demo",
                "commit_sha": "abc123",
                "branch": "feature",
                "format": "lcov",
                "uploader": "local",
            },
            files={"file": ("lcov.info", b"SF:src/api.py\nDA:1,1\nend_of_record\n")},
        )
        self.assertEqual(response.status_code, 200)
        with self.Session() as session:
            parse_job = session.scalar(select(Job).where(Job.type == "parse_upload"))
            process_parse_upload_job(session, parse_job)
            session.commit()

        payload = {
            "repository": {
                "id": 300,
                "name": "demo",
                "full_name": "octo/demo",
                "private": False,
                "default_branch": "main",
                "owner": {"login": "octo"},
            },
            "pull_request": {
                "number": 7,
                "head": {"sha": "abc123", "ref": "feature"},
                "base": {"sha": "base123", "ref": "main"},
                "state": "open",
                "title": "Add API",
            },
        }
        body, headers = self.sign(payload)
        headers["X-GitHub-Event"] = "pull_request"

        response = self.client.post("/api/v1/github/webhook", content=body, headers=headers)

        self.assertEqual(response.status_code, 200)
        with self.Session() as session:
            update_job = session.scalar(select(Job).where(Job.type == "update_github_pr"))
            pull = session.scalar(select(PullRequest))
        self.assertEqual(update_job.payload_json["pull_request_id"], pull.id)

    def test_pull_request_webhook_without_head_report_schedules_pending_update(self):
        with self.Session() as session:
            repository = Repository(
                owner="octo",
                name="demo",
                full_name="octo/demo",
                default_branch="main",
                private=False,
                upload_token_hash=hash_upload_token("cov_secret", "pepper"),
            )
            session.add(repository)
            session.commit()

        payload = {
            "repository": {
                "id": 300,
                "name": "demo",
                "full_name": "octo/demo",
                "private": False,
                "default_branch": "main",
                "owner": {"login": "octo"},
            },
            "pull_request": {
                "number": 7,
                "head": {"sha": "new456", "ref": "feature"},
                "base": {"sha": "base123", "ref": "main"},
                "state": "open",
                "title": "Add API",
            },
        }
        body, headers = self.sign(payload)
        headers["X-GitHub-Event"] = "pull_request"

        response = self.client.post("/api/v1/github/webhook", content=body, headers=headers)

        self.assertEqual(response.status_code, 200)
        with self.Session() as session:
            pending_job = session.scalar(select(Job).where(Job.type == "update_github_pending"))
            pull = session.scalar(select(PullRequest))
        self.assertEqual(pending_job.payload_json["pull_request_id"], pull.id)

    def test_dashboard_links_repo_commit_and_pr_coverage_pages(self):
        with self.Session() as session:
            repository = Repository(
                owner="octo",
                name="demo",
                full_name="octo/demo",
                default_branch="main",
                private=False,
            )
            session.add(repository)
            session.flush()
            from app.models import Commit

            commit = Commit(repository_id=repository.id, sha="abc123", branch="feature")
            session.add(commit)
            session.flush()
            pull = PullRequest(
                repository_id=repository.id,
                github_pr_number=7,
                head_sha="abc123",
                base_sha="base123",
                state="open",
                title="Add API",
            )
            upload = Upload(
                repository_id=repository.id,
                commit_id=commit.id,
                format="lcov",
                storage_path="/tmp/lcov.info",
                status="processed",
            )
            session.add_all([pull, upload])
            session.flush()
            report = CoverageReportRow(
                repository_id=repository.id,
                commit_id=commit.id,
                upload_id=upload.id,
                line_rate=0.5,
                covered_lines=1,
                total_lines=2,
            )
            file_row = FileCoverage(
                path="src/api.py",
                line_rate=0.5,
                covered_lines=1,
                total_lines=2,
            )
            file_row.lines.extend(
                [LineCoverage(line_number=1, hits=1), LineCoverage(line_number=2, hits=0)]
            )
            report.files.append(file_row)
            session.add(report)
            session.flush()
            session.add(
                PrAnnotation(
                    pull_request_id=pull.id,
                    report_id=report.id,
                    patch_covered_lines=1,
                    patch_total_lines=2,
                    patch_line_rate=0.5,
                    status="failure",
                )
            )
            session.commit()

        repo_response = self.client.get("/repos/octo/demo")
        self.assertEqual(repo_response.status_code, 200)
        self.assertIn("/repos/octo/demo/commits/abc123", repo_response.text)
        self.assertIn("/repos/octo/demo/pulls/7", repo_response.text)

        commit_response = self.client.get("/repos/octo/demo/commits/abc123")
        self.assertEqual(commit_response.status_code, 200)
        self.assertIn("50.00%", commit_response.text)
        self.assertIn("src/api.py", commit_response.text)
        self.assertIn("1 / 2", commit_response.text)

        pull_response = self.client.get("/repos/octo/demo/pulls/7")
        self.assertEqual(pull_response.status_code, 200)
        self.assertIn("Add API", pull_response.text)
        self.assertIn("Patch coverage", pull_response.text)
        self.assertIn("50.00%", pull_response.text)


if __name__ == "__main__":
    unittest.main()
