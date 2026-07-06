from __future__ import annotations

import asyncio
import os
import time

from app.config import get_settings
from app.db import SessionLocal
from app.github import GitHubClient, InstallationGitHubClient
from app.models import CoverageReportRow, Installation, Job, PullRequest, Repository
from app.models import Upload
from app.services import (
    claim_next_job,
    mark_job_failed,
    process_parse_upload_job,
    update_github_failure_status,
    update_github_pr,
)


async def run_job(job: Job) -> None:
    settings = get_settings()
    with SessionLocal() as session:
        attached = session.get(Job, job.id)
        try:
            if attached.type == "parse_upload":
                process_parse_upload_job(session, attached)
            elif attached.type == "update_github_pr":
                pull = session.get(PullRequest, int(attached.payload_json["pull_request_id"]))
                report = session.get(CoverageReportRow, int(attached.payload_json["report_id"]))
                repo = session.get(Repository, pull.repository_id)
                installation = (
                    session.get(Installation, repo.installation_id) if repo.installation_id else None
                )
                if installation is None:
                    raise RuntimeError("repository has no GitHub installation")
                private_key = open(settings.github_private_key_path, "r", encoding="utf-8").read()
                token = await GitHubClient(settings.github_app_id, private_key).installation_token(
                    installation.github_installation_id
                )
                annotation = await update_github_pr(
                    session, settings, InstallationGitHubClient(token), pull, report
                )
                if annotation is None:
                    attached.status = "skipped"
            elif attached.type == "update_github_failure":
                pull = session.get(PullRequest, int(attached.payload_json["pull_request_id"]))
                upload = session.get(Upload, int(attached.payload_json["upload_id"]))
                repo = session.get(Repository, pull.repository_id)
                installation = (
                    session.get(Installation, repo.installation_id) if repo.installation_id else None
                )
                if installation is None:
                    raise RuntimeError("repository has no GitHub installation")
                private_key = open(settings.github_private_key_path, "r", encoding="utf-8").read()
                token = await GitHubClient(settings.github_app_id, private_key).installation_token(
                    installation.github_installation_id
                )
                await update_github_failure_status(
                    session, settings, InstallationGitHubClient(token), pull, upload
                )
            else:
                raise RuntimeError("unknown job type: %s" % attached.type)
            if attached.status == "running":
                attached.status = "succeeded"
            attached.locked_at = None
            attached.locked_by = None
            session.commit()
        except Exception as exc:
            mark_job_failed(attached, exc)
            session.commit()


async def main() -> None:
    worker_id = "worker-%s-%s" % (os.getpid(), int(time.time()))
    while True:
        with SessionLocal() as session:
            job = claim_next_job(session, worker_id)
            session.commit()
        if job is None:
            await asyncio.sleep(2)
            continue
        await run_job(job)


if __name__ == "__main__":
    asyncio.run(main())
