import asyncio
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
import app.worker as worker
from app.models import Job, Repository, Upload
from app.security import hash_upload_token
from app.services import create_upload
from app.config import Settings


class WorkerTests(unittest.TestCase):
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

    def test_run_job_marks_successful_parse_job_succeeded(self):
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
            session.flush()
            upload = create_upload(
                session,
                self.settings,
                "Bearer cov_secret",
                "octo/demo",
                "abc123",
                "main",
                None,
                None,
                "lcov",
                "test",
                "lcov.info",
                b"SF:src/api.py\nDA:1,1\nend_of_record\n",
            )
            job = session.scalar(select(Job).where(Job.type == "parse_upload"))
            job.status = "running"
            session.commit()
            job_id = job.id
            upload_id = upload.id

        with patch.object(worker, "SessionLocal", self.Session), patch.object(
            worker, "get_settings", lambda: self.settings
        ):
            asyncio.run(worker.run_job(Job(id=job_id)))

        with self.Session() as session:
            refreshed_job = session.get(Job, job_id)
            refreshed_upload = session.get(Upload, upload_id)

        self.assertEqual(refreshed_job.status, "succeeded")
        self.assertEqual(refreshed_upload.status, "processed")

    def test_run_job_preserves_failed_parse_job_status(self):
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
            session.flush()
            upload = create_upload(
                session,
                self.settings,
                "Bearer cov_secret",
                "octo/demo",
                "abc123",
                "main",
                None,
                None,
                "cobertura",
                "test",
                "coverage.xml",
                b"<not-xml",
            )
            job = session.scalar(select(Job).where(Job.type == "parse_upload"))
            job.status = "running"
            session.commit()
            job_id = job.id
            upload_id = upload.id

        with patch.object(worker, "SessionLocal", self.Session), patch.object(
            worker, "get_settings", lambda: self.settings
        ):
            asyncio.run(worker.run_job(Job(id=job_id)))

        with self.Session() as session:
            refreshed_job = session.get(Job, job_id)
            refreshed_upload = session.get(Upload, upload_id)

        self.assertEqual(refreshed_job.status, "failed")
        self.assertEqual(refreshed_upload.status, "failed")


if __name__ == "__main__":
    unittest.main()
