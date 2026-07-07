import asyncio
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy import BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import Base
from app.github import PullFilePatch
from app.models import (
    Account,
    CoverageReportRow,
    Commit,
    Installation,
    Job,
    PrAnnotation,
    PullRequest,
    Repository,
    Upload,
)
from app.security import hash_upload_token
from app.services import (
    create_upload,
    process_parse_upload_job,
    render_pr_comment,
    sync_installation_repositories_event,
    sync_installation_event,
    update_github_failure_status,
    update_github_pending_coverage,
    update_github_pr,
)


class FakeInstallationClient:
    def __init__(self):
        self.statuses = []
        self.comments = []
        self.pull_payload = {
            "number": 7,
            "head": {"sha": "abc123", "ref": "feature"},
            "base": {"sha": "base123", "ref": "main"},
            "state": "open",
            "title": "Add API",
        }

    async def pull_request(self, owner, repo, number):
        return self.pull_payload

    async def pull_files(self, owner, repo, number):
        return [
            PullFilePatch(
                filename="src/api.py",
                patch="""@@ -8,4 +8,4 @@
 context
+covered
+missed
+ignored
 context
""",
            )
        ]

    async def create_status(self, owner, repo, sha, state, description, target_url, context="coverage/patch"):
        self.statuses.append(
            {
                "owner": owner,
                "repo": repo,
                "sha": sha,
                "state": state,
                "description": description,
                "target_url": target_url,
                "context": context,
            }
        )

    async def upsert_pr_comment(self, owner, repo, pr_number, body, comment_id=None):
        self.comments.append(
            {
                "owner": owner,
                "repo": repo,
                "pr_number": pr_number,
                "body": body,
                "comment_id": comment_id,
            }
        )
        return comment_id or 9876


class ServiceTests(unittest.TestCase):
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
            patch_coverage_minimum=0.8,
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_github_external_ids_use_big_integer_columns(self):
        self.assertIsInstance(PrAnnotation.__table__.c.github_comment_id.type, BigInteger)
        self.assertIsInstance(PrAnnotation.__table__.c.github_check_run_id.type, BigInteger)

    def test_installation_event_upserts_repository_and_generates_upload_token(self):
        payload = {
            "installation": {"id": 100, "account": {"id": 200, "login": "octo"}},
            "sender": {"id": 999, "login": "human-installer"},
            "repositories": [
                {
                    "id": 300,
                    "name": "demo",
                    "full_name": "octo/demo",
                    "private": False,
                    "default_branch": "main",
                }
            ],
        }

        with self.Session() as session:
            tokens = sync_installation_event(session, self.settings, payload)
            session.commit()
            account = session.scalar(select(Account))
            installation = session.scalar(select(Installation))
            repository = session.scalar(select(Repository))

        self.assertEqual(account.login, "octo")
        self.assertEqual(account.github_user_id, 200)
        self.assertEqual(installation.github_installation_id, 100)
        self.assertEqual(repository.full_name, "octo/demo")
        self.assertTrue(tokens["octo/demo"].startswith("cov_"))

    def test_installation_repositories_event_adds_and_deactivates_repositories(self):
        with self.Session() as session:
            account = Account(github_user_id=200, login="octo")
            session.add(account)
            session.flush()
            installation = Installation(github_installation_id=100, account_id=account.id)
            session.add(installation)
            session.flush()
            removed = Repository(
                installation_id=installation.id,
                github_repo_id=301,
                owner="octo",
                name="old",
                full_name="octo/old",
                default_branch="main",
                private=False,
                active=True,
            )
            session.add(removed)
            session.flush()

            tokens = sync_installation_repositories_event(
                session,
                self.settings,
                {
                    "installation": {"id": 100, "account": {"id": 200, "login": "octo"}},
                    "repositories_added": [
                        {
                            "id": 300,
                            "name": "demo",
                            "full_name": "octo/demo",
                            "private": False,
                            "default_branch": "main",
                        }
                    ],
                    "repositories_removed": [{"id": 301, "full_name": "octo/old"}],
                },
            )
            session.commit()

            added = session.scalar(select(Repository).where(Repository.full_name == "octo/demo"))
            old = session.scalar(select(Repository).where(Repository.full_name == "octo/old"))

        self.assertTrue(tokens["octo/demo"].startswith("cov_"))
        self.assertTrue(added.active)
        self.assertFalse(old.active)

    def test_upload_parse_job_persists_line_coverage_and_schedules_pr_update(self):
        token = "cov_secret"
        cobertura = b"""<coverage><packages><package><classes>
<class filename="src/api.py"><lines>
<line number="9" hits="1" />
<line number="10" hits="1" />
<line number="11" hits="0" />
</lines></class>
</classes></package></packages></coverage>"""

        with self.Session() as session:
            repository = Repository(
                owner="octo",
                name="demo",
                full_name="octo/demo",
                default_branch="main",
                private=False,
                upload_token_hash=hash_upload_token(token, "pepper"),
            )
            session.add(repository)
            session.flush()
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
            session.add(pull)
            upload = create_upload(
                session,
                self.settings,
                "Bearer " + token,
                "octo/demo",
                "abc123",
                "feature",
                "base123",
                7,
                "cobertura",
                "test",
                "coverage.xml",
                cobertura,
            )
            parse_job = session.scalar(select(Job).where(Job.type == "parse_upload"))
            process_parse_upload_job(session, parse_job)
            session.commit()

            report = session.scalar(select(CoverageReportRow))
            update_job = session.scalar(select(Job).where(Job.type == "update_github_pr"))
            refreshed_upload = session.get(Upload, upload.id)

        self.assertEqual(refreshed_upload.status, "processed")
        self.assertEqual(report.covered_lines, 2)
        self.assertEqual(report.total_lines, 3)
        self.assertEqual(update_job.payload_json["pull_request_id"], pull.id)

    def test_upload_with_pr_number_upserts_pr_without_prior_webhook(self):
        token = "cov_secret"

        with self.Session() as session:
            repository = Repository(
                owner="octo",
                name="demo",
                full_name="octo/demo",
                default_branch="main",
                private=False,
                upload_token_hash=hash_upload_token(token, "pepper"),
            )
            session.add(repository)
            session.flush()

            create_upload(
                session,
                self.settings,
                "Bearer " + token,
                "octo/demo",
                "abc123",
                "feature",
                "base123",
                7,
                "lcov",
                "test",
                "lcov.info",
                b"SF:src/api.py\nDA:1,1\nend_of_record\n",
                base_branch="main",
            )
            session.commit()

            pull = session.scalar(select(PullRequest))

        self.assertEqual(pull.github_pr_number, 7)
        self.assertEqual(pull.head_sha, "abc123")
        self.assertEqual(pull.head_branch, "feature")
        self.assertEqual(pull.base_sha, "base123")
        self.assertEqual(pull.base_branch, "main")
        self.assertEqual(pull.state, "open")

    def test_parse_job_marks_upload_and_job_failed_for_invalid_report(self):
        token = "cov_secret"

        with self.Session() as session:
            repository = Repository(
                owner="octo",
                name="demo",
                full_name="octo/demo",
                default_branch="main",
                private=False,
                upload_token_hash=hash_upload_token(token, "pepper"),
            )
            session.add(repository)
            session.flush()
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
            session.add(pull)
            upload = create_upload(
                session,
                self.settings,
                "Bearer " + token,
                "octo/demo",
                "abc123",
                "feature",
                "base123",
                7,
                "cobertura",
                "test",
                "coverage.xml",
                b"<not-xml",
            )
            parse_job = session.scalar(select(Job).where(Job.type == "parse_upload"))
            process_parse_upload_job(session, parse_job)
            session.commit()

            refreshed_upload = session.get(Upload, upload.id)
            refreshed_job = session.get(Job, parse_job.id)
            failure_job = session.scalar(select(Job).where(Job.type == "update_github_failure"))

        self.assertEqual(refreshed_upload.status, "failed")
        self.assertIn("invalid Cobertura XML", refreshed_upload.error_message)
        self.assertEqual(refreshed_job.status, "failed")
        self.assertIn("invalid Cobertura XML", refreshed_job.error_message)
        self.assertEqual(failure_job.payload_json["pull_request_id"], pull.id)
        self.assertEqual(failure_job.payload_json["upload_id"], upload.id)

    def test_update_github_failure_status_posts_failure_status(self):
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
                commit_id=1,
                format="cobertura",
                storage_path=str(Path(self.tmpdir.name) / "coverage.xml"),
                status="failed",
                error_message="invalid Cobertura XML: unclosed token",
            )
            session.add_all([pull, upload])
            session.flush()

            fake = FakeInstallationClient()
            asyncio.run(update_github_failure_status(session, self.settings, fake, pull, upload))

        self.assertEqual(fake.statuses[0]["state"], "failure")
        self.assertEqual(fake.statuses[0]["context"], "coverage/patch")
        self.assertIn("Coverage report parsing failed", fake.statuses[0]["description"])

    def test_update_github_failure_status_can_comment_without_commit_status(self):
        settings = Settings(
            database_url="sqlite+pysqlite:///:memory:",
            storage_root=self.tmpdir.name,
            public_base_url="https://coverage.example",
            upload_token_pepper="pepper",
            github_webhook_secret="secret",
            github_commit_status_enabled=False,
        )
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
                commit_id=1,
                format="cobertura",
                storage_path=str(Path(self.tmpdir.name) / "coverage.xml"),
                status="failed",
                error_message="invalid Cobertura XML: unclosed token",
            )
            session.add_all([pull, upload])
            session.flush()

            fake = FakeInstallationClient()
            asyncio.run(update_github_failure_status(session, settings, fake, pull, upload))

        self.assertEqual(fake.statuses, [])
        self.assertEqual(len(fake.comments), 1)
        self.assertIn("Coverage report parsing failed", fake.comments[0]["body"])
        self.assertIn("invalid Cobertura XML", fake.comments[0]["body"])

    def test_update_github_pr_computes_patch_coverage_and_records_annotation(self):
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
                format="cobertura",
                storage_path=str(Path(self.tmpdir.name) / "coverage.xml"),
                status="processed",
            )
            session.add_all([pull, upload])
            session.flush()
            report = CoverageReportRow(
                repository_id=repository.id,
                commit_id=commit.id,
                upload_id=upload.id,
                line_rate=2 / 3,
                covered_lines=2,
                total_lines=3,
            )
            from app.models import FileCoverage, LineCoverage

            file_row = FileCoverage(
                path="src/api.py",
                line_rate=2 / 3,
                covered_lines=2,
                total_lines=3,
            )
            file_row.lines.extend(
                [
                    LineCoverage(line_number=9, hits=1),
                    LineCoverage(line_number=10, hits=1),
                    LineCoverage(line_number=11, hits=0),
                ]
            )
            report.files.append(file_row)
            session.add(report)
            session.flush()

            fake = FakeInstallationClient()
            annotation = asyncio.run(update_github_pr(session, self.settings, fake, pull, report))
            session.commit()

            stored = session.get(PrAnnotation, annotation.id)

        self.assertEqual(fake.statuses[0]["state"], "failure")
        self.assertEqual(fake.statuses[0]["context"], "coverage/patch")
        self.assertIn("66.67%", fake.statuses[0]["description"])
        self.assertIn("| Metric | Covered | Coverage |", fake.comments[0]["body"])
        self.assertIn("| Covered changed lines | 2 / 3 | 66.67% |", fake.comments[0]["body"])
        self.assertIn("| Project coverage | 2 / 3 | 66.67% |", fake.comments[0]["body"])
        self.assertIn("| src/api.py | 2 / 3 | 66.67% |", fake.comments[0]["body"])
        self.assertEqual(stored.patch_covered_lines, 2)
        self.assertEqual(stored.patch_total_lines, 3)

    def test_render_pr_comment_includes_unmatched_warnings(self):
        from app.coverage import PatchCoverageResult

        result = PatchCoverageResult(
            patch_covered_lines=0,
            patch_total_lines=0,
            unmatched_files=["docs/readme.md"],
            warnings=["docs/readme.md did not match any coverage file"],
        )

        body = render_pr_comment(
            result,
            project_covered_lines=14,
            project_total_lines=17,
            target=0.8,
            url="https://coverage.example/repos/octo/demo/pulls/7",
        )

        self.assertIn("Covered changed lines | 0 / 0 | 100.00%", body)
        self.assertIn("Project coverage | 14 / 17 | 82.35%", body)
        self.assertIn("No coverable changed lines found.", body)
        self.assertIn("docs/readme.md did not match any coverage file", body)

    def test_update_github_pr_skips_stale_upload_when_pr_head_changed(self):
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
                storage_path=str(Path(self.tmpdir.name) / "lcov.info"),
                status="processed",
            )
            session.add_all([pull, upload])
            session.flush()
            report = CoverageReportRow(
                repository_id=repository.id,
                commit_id=commit.id,
                upload_id=upload.id,
                line_rate=1.0,
                covered_lines=1,
                total_lines=1,
            )
            session.add(report)
            session.flush()

            fake = FakeInstallationClient()
            fake.pull_payload = {
                "number": 7,
                "head": {"sha": "new456", "ref": "feature"},
                "base": {"sha": "base123", "ref": "main"},
                "state": "open",
                "title": "Add API",
            }
            annotation = asyncio.run(update_github_pr(session, self.settings, fake, pull, report))
            session.commit()

            refreshed_pull = session.get(PullRequest, pull.id)

        self.assertIsNone(annotation)
        self.assertEqual(refreshed_pull.head_sha, "new456")
        self.assertEqual(fake.statuses, [])
        self.assertEqual(fake.comments, [])

    def test_update_github_pr_can_comment_without_commit_status(self):
        settings = Settings(
            database_url="sqlite+pysqlite:///:memory:",
            storage_root=self.tmpdir.name,
            public_base_url="https://coverage.example",
            upload_token_pepper="pepper",
            github_webhook_secret="secret",
            patch_coverage_minimum=0.8,
            github_commit_status_enabled=False,
        )
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
                format="cobertura",
                storage_path=str(Path(self.tmpdir.name) / "coverage.xml"),
                status="processed",
            )
            session.add_all([pull, upload])
            session.flush()
            report = CoverageReportRow(
                repository_id=repository.id,
                commit_id=commit.id,
                upload_id=upload.id,
                line_rate=1.0,
                covered_lines=1,
                total_lines=1,
            )
            from app.models import FileCoverage, LineCoverage

            file_row = FileCoverage(path="src/api.py", line_rate=1.0, covered_lines=1, total_lines=1)
            file_row.lines.append(LineCoverage(line_number=9, hits=1))
            report.files.append(file_row)
            session.add(report)
            session.flush()

            fake = FakeInstallationClient()
            annotation = asyncio.run(update_github_pr(session, settings, fake, pull, report))
            session.commit()

        self.assertEqual(fake.statuses, [])
        self.assertEqual(len(fake.comments), 1)
        self.assertIsNotNone(annotation)

    def test_update_github_pending_coverage_reuses_comment_for_current_head(self):
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
            old_commit = Commit(repository_id=repository.id, sha="old123", branch="feature")
            session.add(old_commit)
            session.flush()
            pull = PullRequest(
                repository_id=repository.id,
                github_pr_number=7,
                head_sha="new456",
                base_sha="base123",
                state="open",
                title="Add API",
            )
            upload = Upload(
                repository_id=repository.id,
                commit_id=old_commit.id,
                format="lcov",
                storage_path=str(Path(self.tmpdir.name) / "lcov.info"),
                status="processed",
            )
            session.add_all([pull, upload])
            session.flush()
            old_report = CoverageReportRow(
                repository_id=repository.id,
                commit_id=old_commit.id,
                upload_id=upload.id,
                line_rate=1.0,
                covered_lines=1,
                total_lines=1,
            )
            session.add(old_report)
            session.flush()
            annotation = PrAnnotation(
                pull_request_id=pull.id,
                report_id=old_report.id,
                patch_covered_lines=1,
                patch_total_lines=1,
                patch_line_rate=1.0,
                github_comment_id=12345,
                status="success",
            )
            session.add(annotation)
            session.flush()

            fake = FakeInstallationClient()
            fake.pull_payload = {
                "number": 7,
                "head": {"sha": "new456", "ref": "feature"},
                "base": {"sha": "base123", "ref": "main"},
                "state": "open",
                "title": "Add API",
            }
            asyncio.run(update_github_pending_coverage(session, self.settings, fake, pull))

        self.assertEqual(fake.statuses[0]["sha"], "new456")
        self.assertEqual(fake.statuses[0]["state"], "pending")
        self.assertIn("Waiting for coverage report", fake.statuses[0]["description"])
        self.assertEqual(fake.comments[0]["comment_id"], 12345)
        self.assertIn("Waiting for coverage report", fake.comments[0]["body"])
        self.assertIn("new456", fake.comments[0]["body"])

    def test_update_github_pending_coverage_skips_when_head_report_exists(self):
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
            commit = Commit(repository_id=repository.id, sha="new456", branch="feature")
            session.add(commit)
            session.flush()
            pull = PullRequest(
                repository_id=repository.id,
                github_pr_number=7,
                head_sha="new456",
                base_sha="base123",
                state="open",
                title="Add API",
            )
            upload = Upload(
                repository_id=repository.id,
                commit_id=commit.id,
                format="lcov",
                storage_path=str(Path(self.tmpdir.name) / "lcov.info"),
                status="processed",
            )
            session.add_all([pull, upload])
            session.flush()
            session.add(
                CoverageReportRow(
                    repository_id=repository.id,
                    commit_id=commit.id,
                    upload_id=upload.id,
                    line_rate=1.0,
                    covered_lines=1,
                    total_lines=1,
                )
            )
            session.flush()

            fake = FakeInstallationClient()
            fake.pull_payload = {
                "number": 7,
                "head": {"sha": "new456", "ref": "feature"},
                "base": {"sha": "base123", "ref": "main"},
                "state": "open",
                "title": "Add API",
            }
            asyncio.run(update_github_pending_coverage(session, self.settings, fake, pull))

        self.assertEqual(fake.statuses, [])
        self.assertEqual(fake.comments, [])


if __name__ == "__main__":
    unittest.main()
