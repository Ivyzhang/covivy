from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.coverage import CoverageReport, compute_patch_coverage, parse_report
from app.github import InstallationGitHubClient, changed_lines_from_pull_files
from app.models import (
    Account,
    Commit,
    CoverageReportRow,
    FileCoverage,
    Installation,
    Job,
    LineCoverage,
    PrAnnotation,
    PullRequest,
    Repository,
    Upload,
)
from app.security import generate_upload_token, hash_upload_token, verify_upload_token
from app.storage import store_upload


def get_repository_by_full_name(session: Session, full_name: str) -> Optional[Repository]:
    owner, name = full_name.split("/", 1)
    return session.scalar(
        select(Repository).where(Repository.owner == owner, Repository.name == name)
    )


def upsert_commit(
    session: Session,
    repository: Repository,
    sha: str,
    branch: Optional[str] = None,
    parent_sha: Optional[str] = None,
) -> Commit:
    commit = session.scalar(
        select(Commit).where(Commit.repository_id == repository.id, Commit.sha == sha)
    )
    if commit is None:
        commit = Commit(repository_id=repository.id, sha=sha)
        session.add(commit)
    commit.branch = branch
    commit.parent_sha = parent_sha
    return commit


def upsert_pull_request_from_github_payload(
    session: Session, repository: Repository, payload: Dict
) -> PullRequest:
    pr_number = int(payload["number"])
    pull = session.scalar(
        select(PullRequest).where(
            PullRequest.repository_id == repository.id,
            PullRequest.github_pr_number == pr_number,
        )
    )
    if pull is None:
        pull = PullRequest(repository_id=repository.id, github_pr_number=pr_number)
        session.add(pull)
    pull.head_sha = payload["head"]["sha"]
    pull.base_sha = payload["base"]["sha"]
    pull.head_branch = payload["head"]["ref"]
    pull.base_branch = payload["base"]["ref"]
    pull.state = payload["state"]
    pull.title = payload.get("title")
    return pull


def upsert_pull_request_from_upload(
    session: Session,
    repository: Repository,
    pr_number: int,
    head_sha: str,
    head_branch: Optional[str],
    base_sha: Optional[str],
    base_branch: Optional[str],
) -> PullRequest:
    payload = {
        "number": pr_number,
        "head": {"sha": head_sha, "ref": head_branch or ""},
        "base": {"sha": base_sha or "", "ref": base_branch or ""},
        "state": "open",
        "title": None,
    }
    return upsert_pull_request_from_github_payload(session, repository, payload)


def enqueue_job(session: Session, job_type: str, payload: Dict, run_after: Optional[datetime] = None) -> Job:
    job = Job(type=job_type, payload_json=payload, run_after=run_after or datetime.utcnow())
    session.add(job)
    return job


def upsert_installed_repository(
    session: Session,
    installation: Installation,
    repo_data: Dict,
    upload_token_pepper: str,
) -> Optional[str]:
    if repo_data.get("owner") and repo_data["owner"].get("login"):
        owner = repo_data["owner"]["login"]
        name = repo_data["name"]
    else:
        owner, name = repo_data["full_name"].split("/", 1)
    repository = session.scalar(
        select(Repository).where(Repository.owner == owner, Repository.name == name)
    )
    raw_token = None
    if repository is None:
        repository = Repository(owner=owner, name=name, full_name=repo_data["full_name"])
        session.add(repository)
    repository.installation_id = installation.id
    repository.github_repo_id = repo_data["id"]
    repository.default_branch = repo_data.get("default_branch") or repository.default_branch or "main"
    repository.private = bool(repo_data.get("private"))
    repository.active = True
    if not repository.upload_token_hash:
        raw_token = generate_upload_token()
        repository.upload_token_hash = hash_upload_token(raw_token, upload_token_pepper)
    return raw_token


def sync_installation_event(session: Session, settings: Settings, payload: Dict) -> Dict[str, str]:
    account_data = payload.get("installation", {}).get("account") or payload.get("sender") or {}
    github_user_id = account_data.get("id") or payload["installation"]["account"]["id"]
    login = account_data.get("login") or payload["installation"]["account"]["login"]
    account = session.scalar(select(Account).where(Account.github_user_id == github_user_id))
    if account is None:
        account = Account(github_user_id=github_user_id, login=login)
        session.add(account)
        session.flush()
    installation = session.scalar(
        select(Installation).where(
            Installation.github_installation_id == payload["installation"]["id"]
        )
    )
    if installation is None:
        installation = Installation(
            github_installation_id=payload["installation"]["id"], account_id=account.id
        )
        session.add(installation)
        session.flush()

    generated_tokens: Dict[str, str] = {}
    for repo_data in payload.get("repositories") or []:
        token = upsert_installed_repository(
            session, installation, repo_data, settings.upload_token_pepper
        )
        if token:
            generated_tokens[repo_data["full_name"]] = token
    return generated_tokens


def sync_installation_repositories_event(session: Session, settings: Settings, payload: Dict) -> Dict[str, str]:
    installation = session.scalar(
        select(Installation).where(
            Installation.github_installation_id == payload["installation"]["id"]
        )
    )
    if installation is None:
        account_data = payload["installation"]["account"]
        account = session.scalar(select(Account).where(Account.github_user_id == account_data["id"]))
        if account is None:
            account = Account(github_user_id=account_data["id"], login=account_data["login"])
            session.add(account)
            session.flush()
        installation = Installation(
            github_installation_id=payload["installation"]["id"], account_id=account.id
        )
        session.add(installation)
        session.flush()

    generated_tokens: Dict[str, str] = {}
    for repo_data in payload.get("repositories_added") or []:
        token = upsert_installed_repository(
            session, installation, repo_data, settings.upload_token_pepper
        )
        if token:
            generated_tokens[repo_data["full_name"]] = token
    for repo_data in payload.get("repositories_removed") or []:
        owner, name = repo_data["full_name"].split("/", 1)
        repository = session.scalar(
            select(Repository).where(Repository.owner == owner, Repository.name == name)
        )
        if repository is not None:
            repository.active = False
    return generated_tokens


def create_upload(
    session: Session,
    settings: Settings,
    authorization: str,
    repository_full_name: str,
    commit_sha: str,
    branch: Optional[str],
    parent_sha: Optional[str],
    pr_number: Optional[int],
    format_name: str,
    uploader: Optional[str],
    filename: str,
    data: bytes,
    base_branch: Optional[str] = None,
) -> Upload:
    if not authorization.startswith("Bearer "):
        raise PermissionError("missing bearer token")
    repository = get_repository_by_full_name(session, repository_full_name)
    if repository is None:
        raise LookupError("repository not found")
    token = authorization.split(" ", 1)[1]
    if not verify_upload_token(token, settings.upload_token_pepper, repository.upload_token_hash):
        raise PermissionError("invalid upload token")
    commit = upsert_commit(session, repository, commit_sha, branch, parent_sha)
    if pr_number is not None:
        upsert_pull_request_from_upload(
            session,
            repository,
            pr_number,
            commit_sha,
            branch,
            parent_sha,
            base_branch,
        )
    session.flush()
    path = store_upload(settings.storage_root, repository.id, commit_sha, filename, data)
    upload = Upload(
        repository_id=repository.id,
        commit_id=commit.id,
        format=format_name,
        storage_path=path,
        uploader=uploader,
        status="queued",
    )
    session.add(upload)
    session.flush()
    payload = {"upload_id": upload.id}
    if pr_number is not None:
        payload["pr_number"] = pr_number
    enqueue_job(session, "parse_upload", payload)
    return upload


def rotate_repository_upload_token(
    session: Session, settings: Settings, owner: str, name: str
) -> str:
    repository = session.scalar(
        select(Repository).where(Repository.owner == owner, Repository.name == name)
    )
    if repository is None:
        raise LookupError("repository not found")
    token = generate_upload_token()
    repository.upload_token_hash = hash_upload_token(token, settings.upload_token_pepper)
    return token


def find_related_pull_request(
    session: Session, upload: Upload, pr_number: Optional[int] = None
) -> Optional[PullRequest]:
    pull_request = None
    if pr_number is not None:
        pull_request = session.scalar(
            select(PullRequest).where(
                PullRequest.repository_id == upload.repository_id,
                PullRequest.github_pr_number == pr_number,
            )
        )
    if pull_request is None:
        commit = session.get(Commit, upload.commit_id)
        pull_request = session.scalar(
            select(PullRequest).where(
                PullRequest.repository_id == upload.repository_id,
                PullRequest.head_sha == commit.sha,
            )
        )
    return pull_request


def persist_report(session: Session, upload: Upload, report: CoverageReport) -> CoverageReportRow:
    row = CoverageReportRow(
        repository_id=upload.repository_id,
        commit_id=upload.commit_id,
        upload_id=upload.id,
        line_rate=report.line_rate,
        covered_lines=report.covered_lines,
        total_lines=report.total_lines,
    )
    for file in report.files:
        file_row = FileCoverage(
            path=file.path,
            line_rate=file.line_rate,
            covered_lines=file.covered_lines,
            total_lines=file.total_lines,
        )
        for line in file.lines:
            file_row.lines.append(
                LineCoverage(
                    line_number=line.number,
                    hits=line.hits,
                    branch=line.branch,
                    condition_coverage=line.condition_coverage,
                )
            )
        row.files.append(file_row)
    session.add(row)
    return row


def process_parse_upload_job(session: Session, job: Job) -> None:
    upload_id = int(job.payload_json["upload_id"])
    upload = session.get(Upload, upload_id)
    if upload is None:
        raise LookupError("upload not found")
    payload = Path(upload.storage_path).read_bytes()
    try:
        report = parse_report(upload.format, payload)
    except Exception as exc:
        upload.status = "failed"
        upload.error_message = str(exc)
        job.status = "failed"
        job.error_message = str(exc)
        job.locked_at = None
        job.locked_by = None
        pull_request = find_related_pull_request(session, upload, job.payload_json.get("pr_number"))
        if pull_request is not None:
            enqueue_job(
                session,
                "update_github_failure",
                {"pull_request_id": pull_request.id, "upload_id": upload.id},
            )
        return
    report_row = persist_report(session, upload, report)
    upload.status = "processed"
    session.flush()

    pull_request = find_related_pull_request(session, upload, job.payload_json.get("pr_number"))
    if pull_request is not None:
        enqueue_job(
            session,
            "update_github_pr",
            {"pull_request_id": pull_request.id, "report_id": report_row.id},
        )


def latest_report_for_commit(session: Session, repository_id: int, sha: str) -> Optional[CoverageReportRow]:
    return session.scalar(
        select(CoverageReportRow)
        .join(Commit, Commit.id == CoverageReportRow.commit_id)
        .where(CoverageReportRow.repository_id == repository_id, Commit.sha == sha)
        .order_by(CoverageReportRow.created_at.desc())
        .limit(1)
    )


def claim_next_job(session: Session, worker_id: str) -> Optional[Job]:
    job = session.scalar(
        select(Job)
        .where(Job.status == "queued", Job.run_after <= datetime.utcnow())
        .order_by(Job.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    job.status = "running"
    job.locked_at = datetime.utcnow()
    job.locked_by = worker_id
    job.attempts += 1
    return job


def mark_job_failed(job: Job, exc: Exception) -> None:
    job.error_message = str(exc)
    if job.attempts >= job.max_attempts:
        job.status = "failed"
    else:
        job.status = "queued"
        job.run_after = datetime.utcnow() + timedelta(seconds=min(300, 2 ** job.attempts))
    job.locked_at = None
    job.locked_by = None


def load_report_shape(report_row: CoverageReportRow) -> CoverageReport:
    from app.coverage import CoveredFile, CoveredLine

    files = []
    for file_row in report_row.files:
        files.append(
            CoveredFile(
                path=file_row.path,
                lines=[
                    CoveredLine(
                        number=line.line_number,
                        hits=line.hits,
                        branch=line.branch,
                        condition_coverage=line.condition_coverage,
                    )
                    for line in file_row.lines
                ],
            )
        )
    return CoverageReport(files=files)


def render_pr_comment(
    result,
    project_covered_lines: int,
    project_total_lines: int,
    target: float,
    url: str,
) -> str:
    status = "passed" if result.patch_line_rate >= target else "failed"

    def coverage_percent(covered: int, total: int) -> str:
        rate = 1.0 if total == 0 else covered / total
        return "%.2f%%" % (rate * 100)

    def covered_count(covered: int, total: int) -> str:
        return "%s / %s" % (covered, total)

    lines = [
        "<!-- coverage-service:pr-comment -->",
        "",
        "## Coverage Report",
        "",
        "| Metric | Covered | Coverage |",
        "| --- | ---: | ---: |",
        "| Covered changed lines | %s | %s |"
        % (
            covered_count(result.patch_covered_lines, result.patch_total_lines),
            coverage_percent(result.patch_covered_lines, result.patch_total_lines),
        ),
        "| Project coverage | %s | %s |"
        % (
            covered_count(project_covered_lines, project_total_lines),
            coverage_percent(project_covered_lines, project_total_lines),
        ),
        "",
    ]
    if result.files:
        lines.extend(
            [
                "### Changed files",
                "",
                "| File | Covered | Coverage |",
                "| --- | ---: | ---: |",
            ]
        )
        for file_result in result.files[:10]:
            lines.append(
                "| %s | %s | %s |"
                % (
                    file_result.path,
                    covered_count(
                        file_result.patch_covered_lines,
                        file_result.patch_total_lines,
                    ),
                    coverage_percent(
                        file_result.patch_covered_lines,
                        file_result.patch_total_lines,
                    ),
                )
            )
        lines.append("")
    if result.patch_total_lines == 0:
        lines.extend(["No coverable changed lines found.", ""])
    if result.warnings:
        lines.extend(["### Warnings", ""])
        for warning in result.warnings[:10]:
            lines.append("- %s" % warning)
        lines.append("")
    lines.extend(
        [
            "Status: %s. Patch coverage target is %.2f%%." % (status, target * 100),
            "",
            "[View full report](%s)" % url,
        ]
    )
    return "\n".join(lines)


def render_failure_pr_comment(message: str, url: str) -> str:
    return "\n".join(
        [
            "<!-- coverage-service:pr-comment -->",
            "",
            "## Coverage Report",
            "",
            "Status: failed. %s" % message,
            "",
            "[View full report](%s)" % url,
        ]
    )


def render_pending_pr_comment(head_sha: str, url: str) -> str:
    short_sha = head_sha[:12]
    return "\n".join(
        [
            "<!-- coverage-service:pr-comment -->",
            "",
            "## Coverage Report",
            "",
            "Waiting for coverage report for head commit `%s`." % short_sha,
            "",
            "[View full report](%s)" % url,
        ]
    )


async def update_github_pr(
    session: Session,
    settings: Settings,
    installation_client: InstallationGitHubClient,
    pull_request: PullRequest,
    report_row: CoverageReportRow,
) -> Optional[PrAnnotation]:
    repository = session.get(Repository, pull_request.repository_id)
    pr_payload = await installation_client.pull_request(
        repository.owner, repository.name, pull_request.github_pr_number
    )
    pull_request = upsert_pull_request_from_github_payload(session, repository, pr_payload)
    commit = session.get(Commit, report_row.commit_id)
    if commit.sha != pull_request.head_sha:
        return None
    files = await installation_client.pull_files(
        repository.owner, repository.name, pull_request.github_pr_number
    )
    changed = changed_lines_from_pull_files(files)
    result = compute_patch_coverage(load_report_shape(report_row), changed)
    target_url = "%s/repos/%s/%s/pulls/%s" % (
        settings.public_base_url.rstrip("/"),
        repository.owner,
        repository.name,
        pull_request.github_pr_number,
    )
    description = result.description_for_target(settings.patch_coverage_minimum)
    state = result.status_for_target(settings.patch_coverage_minimum)
    if settings.github_commit_status_enabled:
        await installation_client.create_status(
            repository.owner,
            repository.name,
            pull_request.head_sha,
            state,
            description,
            target_url,
        )

    annotation = session.scalar(
        select(PrAnnotation)
        .where(PrAnnotation.pull_request_id == pull_request.id)
        .order_by(PrAnnotation.updated_at.desc())
        .limit(1)
    )
    body = render_pr_comment(
        result,
        report_row.covered_lines,
        report_row.total_lines,
        settings.patch_coverage_minimum,
        target_url,
    )
    comment_id = await installation_client.upsert_pr_comment(
        repository.owner,
        repository.name,
        pull_request.github_pr_number,
        body,
        annotation.github_comment_id if annotation else None,
    )
    if annotation is None:
        annotation = PrAnnotation(pull_request_id=pull_request.id, report_id=report_row.id)
        session.add(annotation)
    annotation.report_id = report_row.id
    annotation.patch_covered_lines = result.patch_covered_lines
    annotation.patch_total_lines = result.patch_total_lines
    annotation.patch_line_rate = result.patch_line_rate
    annotation.github_comment_id = comment_id
    annotation.status = state
    return annotation


async def update_github_pending_coverage(
    session: Session,
    settings: Settings,
    installation_client: InstallationGitHubClient,
    pull_request: PullRequest,
) -> None:
    repository = session.get(Repository, pull_request.repository_id)
    pr_payload = await installation_client.pull_request(
        repository.owner, repository.name, pull_request.github_pr_number
    )
    pull_request = upsert_pull_request_from_github_payload(session, repository, pr_payload)
    if latest_report_for_commit(session, repository.id, pull_request.head_sha) is not None:
        return
    target_url = "%s/repos/%s/%s/pulls/%s" % (
        settings.public_base_url.rstrip("/"),
        repository.owner,
        repository.name,
        pull_request.github_pr_number,
    )
    description = "Waiting for coverage report for head %s" % pull_request.head_sha[:12]
    if settings.github_commit_status_enabled:
        await installation_client.create_status(
            repository.owner,
            repository.name,
            pull_request.head_sha,
            "pending",
            description,
            target_url,
        )
    annotation = session.scalar(
        select(PrAnnotation)
        .where(PrAnnotation.pull_request_id == pull_request.id)
        .order_by(PrAnnotation.updated_at.desc())
        .limit(1)
    )
    await installation_client.upsert_pr_comment(
        repository.owner,
        repository.name,
        pull_request.github_pr_number,
        render_pending_pr_comment(pull_request.head_sha, target_url),
        annotation.github_comment_id if annotation else None,
    )


async def update_github_failure_status(
    session: Session,
    settings: Settings,
    installation_client: InstallationGitHubClient,
    pull_request: PullRequest,
    upload: Upload,
) -> None:
    repository = session.get(Repository, pull_request.repository_id)
    target_url = "%s/repos/%s/%s/pulls/%s" % (
        settings.public_base_url.rstrip("/"),
        repository.owner,
        repository.name,
        pull_request.github_pr_number,
    )
    message = "Coverage report parsing failed"
    if upload.error_message:
        message = "%s: %s" % (message, upload.error_message)
    if settings.github_commit_status_enabled:
        await installation_client.create_status(
            repository.owner,
            repository.name,
            pull_request.head_sha,
            "failure",
            message,
            target_url,
        )
    else:
        await installation_client.upsert_pr_comment(
            repository.owner,
            repository.name,
            pull_request.github_pr_number,
            render_failure_pr_comment(message, target_url),
        )
