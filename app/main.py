from __future__ import annotations

from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import Commit, CoverageReportRow, PrAnnotation, PullRequest, Repository
from app.security import verify_github_signature
from app.services import (
    create_upload,
    enqueue_job,
    latest_report_for_commit,
    rotate_repository_upload_token,
    sync_installation_event,
    sync_installation_repositories_event,
    upsert_commit,
)

app = FastAPI(title="Coverage Service")


def percent(value: float) -> str:
    return "%.2f%%" % (value * 100)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/api/v1/uploads")
async def upload_coverage(
    repository: str = Form(...),
    commit_sha: str = Form(...),
    branch: Optional[str] = Form(None),
    base_sha: Optional[str] = Form(None),
    base_branch: Optional[str] = Form(None),
    parent_sha: Optional[str] = Form(None),
    pr_number: Optional[int] = Form(None),
    format: str = Form(...),
    uploader: Optional[str] = Form(None),
    file: UploadFile = File(...),
    authorization: str = Header(""),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    try:
        upload = create_upload(
            session,
            settings,
            authorization,
            repository,
            commit_sha,
            branch,
            base_sha or parent_sha,
            pr_number,
            format,
            uploader,
            file.filename or "coverage",
            await file.read(),
            base_branch=base_branch,
        )
        session.commit()
        return {"upload_id": "up_%s" % upload.id, "commit_sha": commit_sha, "status": upload.status}
    except PermissionError as exc:
        session.rollback()
        raise HTTPException(status_code=401, detail=str(exc))
    except LookupError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/v1/repos/{owner}/{repo}")
def get_repo(owner: str, repo: str, session: Session = Depends(get_session)):
    repository = session.scalar(
        select(Repository).where(Repository.owner == owner, Repository.name == repo)
    )
    if repository is None:
        raise HTTPException(status_code=404, detail="repository not found")
    return {
        "id": repository.id,
        "full_name": repository.full_name,
        "default_branch": repository.default_branch,
        "private": repository.private,
    }


@app.post("/api/v1/repos/{owner}/{repo}/upload-token")
def rotate_upload_token(
    owner: str,
    repo: str,
    authorization: str = Header(""),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    if not authorization.startswith("Bearer ") or authorization.split(" ", 1)[1] != settings.admin_token:
        raise HTTPException(status_code=401, detail="invalid admin token")
    try:
        token = rotate_repository_upload_token(session, settings, owner, repo)
        session.commit()
        return {"repository": "%s/%s" % (owner, repo), "upload_token": token}
    except LookupError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/v1/repos/{owner}/{repo}/commits/{sha}")
def get_commit(owner: str, repo: str, sha: str, session: Session = Depends(get_session)):
    repository = session.scalar(
        select(Repository).where(Repository.owner == owner, Repository.name == repo)
    )
    if repository is None:
        raise HTTPException(status_code=404, detail="repository not found")
    report = latest_report_for_commit(session, repository.id, sha)
    if report is None:
        raise HTTPException(status_code=404, detail="coverage report not found")
    return {
        "sha": sha,
        "line_rate": report.line_rate,
        "covered_lines": report.covered_lines,
        "total_lines": report.total_lines,
        "files": [
            {
                "path": item.path,
                "line_rate": item.line_rate,
                "covered_lines": item.covered_lines,
                "total_lines": item.total_lines,
            }
            for item in report.files
        ],
    }


@app.get("/api/v1/repos/{owner}/{repo}/pulls/{number}")
def get_pull(owner: str, repo: str, number: int, session: Session = Depends(get_session)):
    repository = session.scalar(
        select(Repository).where(Repository.owner == owner, Repository.name == repo)
    )
    if repository is None:
        raise HTTPException(status_code=404, detail="repository not found")
    pull = session.scalar(
        select(PullRequest).where(
            PullRequest.repository_id == repository.id,
            PullRequest.github_pr_number == number,
        )
    )
    if pull is None:
        raise HTTPException(status_code=404, detail="pull request not found")
    report = latest_report_for_commit(session, repository.id, pull.head_sha)
    return {
        "number": pull.github_pr_number,
        "title": pull.title,
        "state": pull.state,
        "head_sha": pull.head_sha,
        "base_sha": pull.base_sha,
        "coverage": None
        if report is None
        else {
            "line_rate": report.line_rate,
            "covered_lines": report.covered_lines,
            "total_lines": report.total_lines,
        },
    }


@app.post("/api/v1/github/webhook")
async def github_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None),
    x_github_event: Optional[str] = Header(None),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    body = await request.body()
    if not verify_github_signature(body, x_hub_signature_256, settings.github_webhook_secret):
        raise HTTPException(status_code=401, detail="invalid signature")
    payload = await request.json()
    event = x_github_event or ""
    if event == "installation":
        sync_installation_event(session, settings, payload)
    elif event == "installation_repositories":
        sync_installation_repositories_event(session, settings, payload)
    elif event == "pull_request":
        repo_data = payload["repository"]
        owner = repo_data["owner"]["login"]
        name = repo_data["name"]
        repository = session.scalar(
            select(Repository).where(Repository.owner == owner, Repository.name == name)
        )
        if repository is None:
            repository = Repository(
                owner=owner,
                name=name,
                full_name=repo_data["full_name"],
                github_repo_id=repo_data["id"],
                default_branch=repo_data.get("default_branch") or "main",
                private=repo_data.get("private") or False,
            )
            session.add(repository)
            session.flush()
        pr = payload["pull_request"]
        pull = session.scalar(
            select(PullRequest).where(
                PullRequest.repository_id == repository.id,
                PullRequest.github_pr_number == pr["number"],
            )
        )
        if pull is None:
            pull = PullRequest(repository_id=repository.id, github_pr_number=pr["number"])
            session.add(pull)
        pull.head_sha = pr["head"]["sha"]
        pull.base_sha = pr["base"]["sha"]
        pull.head_branch = pr["head"]["ref"]
        pull.base_branch = pr["base"]["ref"]
        pull.state = pr["state"]
        pull.title = pr["title"]
        upsert_commit(session, repository, pull.head_sha, pull.head_branch, pull.base_sha)
        report = latest_report_for_commit(session, repository.id, pull.head_sha)
        if report is not None:
            enqueue_job(session, "update_github_pr", {"pull_request_id": pull.id, "report_id": report.id})
        elif pull.state == "open":
            enqueue_job(session, "update_github_pending", {"pull_request_id": pull.id})
    elif event == "push":
        repo_data = payload["repository"]
        owner, name = repo_data["full_name"].split("/", 1)
        repository = session.scalar(
            select(Repository).where(Repository.owner == owner, Repository.name == name)
        )
        if repository is not None:
            upsert_commit(session, repository, payload["after"], payload.get("ref", "").split("/")[-1])
    session.commit()
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def dashboard(session: Session = Depends(get_session)):
    repositories = session.scalars(select(Repository).order_by(Repository.full_name)).all()
    rows = "\n".join(
        '<li><a href="/repos/{owner}/{name}">{full_name}</a> '
        '<code>POST /api/v1/repos/{owner}/{name}/upload-token</code></li>'.format(
            owner=repo.owner, name=repo.name, full_name=repo.full_name
        )
        for repo in repositories
    )
    return HTMLResponse(
        "<html><body><h1>Coverage Service</h1><h2>Repositories</h2><ul>%s</ul></body></html>"
        % rows
    )


@app.get("/repos/{owner}/{repo}", response_class=HTMLResponse)
def repo_dashboard(owner: str, repo: str, session: Session = Depends(get_session)):
    repository = session.scalar(
        select(Repository).where(Repository.owner == owner, Repository.name == repo)
    )
    if repository is None:
        raise HTTPException(status_code=404, detail="repository not found")
    reports = session.execute(
        select(CoverageReportRow, Commit)
        .join(Commit, Commit.id == CoverageReportRow.commit_id)
        .where(CoverageReportRow.repository_id == repository.id)
        .order_by(CoverageReportRow.created_at.desc())
        .limit(20)
    ).all()
    pulls = session.scalars(
        select(PullRequest)
        .where(PullRequest.repository_id == repository.id)
        .order_by(PullRequest.updated_at.desc())
        .limit(20)
    ).all()
    rows = "\n".join(
        '<tr><td><a href="/repos/{owner}/{repo}/commits/{sha}">{sha}</a></td>'
        "<td>{coverage}</td><td>{lines}</td></tr>".format(
            owner=owner,
            repo=repo,
            sha=commit.sha,
            coverage=percent(report.line_rate),
            lines="%s / %s" % (report.covered_lines, report.total_lines),
        )
        for report, commit in reports
    )
    pull_rows = "\n".join(
        '<tr><td><a href="/repos/{owner}/{repo}/pulls/{number}">#{number}</a></td>'
        "<td>{title}</td><td>{state}</td><td>{head}</td></tr>".format(
            owner=owner,
            repo=repo,
            number=pull.github_pr_number,
            title=pull.title or "",
            state=pull.state,
            head=pull.head_sha,
        )
        for pull in pulls
    )
    return HTMLResponse(
        "<html><body><h1>{full_name}</h1>"
        "<h2>Commits</h2><table><tr><th>Commit</th><th>Coverage</th><th>Lines</th></tr>{rows}</table>"
        "<h2>Pull Requests</h2><table><tr><th>PR</th><th>Title</th><th>State</th><th>Head</th></tr>{pull_rows}</table>"
        "</body></html>".format(full_name=repository.full_name, rows=rows, pull_rows=pull_rows)
    )


@app.get("/repos/{owner}/{repo}/commits/{sha}", response_class=HTMLResponse)
def commit_dashboard(owner: str, repo: str, sha: str, session: Session = Depends(get_session)):
    repository = session.scalar(
        select(Repository).where(Repository.owner == owner, Repository.name == repo)
    )
    if repository is None:
        raise HTTPException(status_code=404, detail="repository not found")
    report = latest_report_for_commit(session, repository.id, sha)
    if report is None:
        raise HTTPException(status_code=404, detail="coverage report not found")
    file_rows = "\n".join(
        "<tr><td>{path}</td><td>{coverage}</td><td>{lines}</td></tr>".format(
            path=file.path,
            coverage=percent(file.line_rate),
            lines="%s / %s" % (file.covered_lines, file.total_lines),
        )
        for file in report.files
    )
    return HTMLResponse(
        "<html><body><h1>{repo}@{sha}</h1>"
        "<p>Project coverage: {coverage}</p>"
        "<p>Covered lines: {lines}</p>"
        "<table><tr><th>File</th><th>Coverage</th><th>Lines</th></tr>{file_rows}</table>"
        "</body></html>".format(
            repo=repository.full_name,
            sha=sha,
            coverage=percent(report.line_rate),
            lines="%s / %s" % (report.covered_lines, report.total_lines),
            file_rows=file_rows,
        )
    )


@app.get("/repos/{owner}/{repo}/pulls/{number}", response_class=HTMLResponse)
def pull_dashboard(owner: str, repo: str, number: int, session: Session = Depends(get_session)):
    repository = session.scalar(
        select(Repository).where(Repository.owner == owner, Repository.name == repo)
    )
    if repository is None:
        raise HTTPException(status_code=404, detail="repository not found")
    pull = session.scalar(
        select(PullRequest).where(
            PullRequest.repository_id == repository.id,
            PullRequest.github_pr_number == number,
        )
    )
    if pull is None:
        raise HTTPException(status_code=404, detail="pull request not found")
    report = latest_report_for_commit(session, repository.id, pull.head_sha)
    annotation = None
    if report is not None:
        annotation = session.scalar(
            select(PrAnnotation)
            .where(PrAnnotation.pull_request_id == pull.id, PrAnnotation.report_id == report.id)
            .order_by(PrAnnotation.updated_at.desc())
            .limit(1)
        )
    coverage_html = "<p>No coverage report for head commit yet.</p>"
    if report is not None:
        coverage_html = (
            "<p>Project coverage: {coverage}</p><p>Covered lines: {lines}</p>".format(
                coverage=percent(report.line_rate),
                lines="%s / %s" % (report.covered_lines, report.total_lines),
            )
        )
    patch_html = "<p>No patch coverage computed yet.</p>"
    if annotation is not None:
        patch_html = (
            "<table><tr><th>Metric</th><th>Covered</th><th>Coverage</th></tr>"
            "<tr><td>Covered changed lines</td><td>{patch_lines}</td><td>{patch}</td></tr>"
            "<tr><td>Project coverage</td><td>{project_lines}</td><td>{project}</td></tr>"
            "<tr><td>Status</td><td colspan=\"2\">{status}</td></tr></table>"
        ).format(
            patch=percent(annotation.patch_line_rate),
            patch_lines="%s / %s" % (annotation.patch_covered_lines, annotation.patch_total_lines),
            project=percent(report.line_rate),
            project_lines="%s / %s" % (report.covered_lines, report.total_lines),
            status=annotation.status,
        )
    return HTMLResponse(
        "<html><body><h1>PR #{number}: {title}</h1>"
        "<p>State: {state}</p><p>Head: {head}</p><p>Base: {base}</p>"
        "<h2>Coverage</h2>{coverage}"
        "<h2>Patch</h2>{patch}"
        "</body></html>".format(
            number=pull.github_pr_number,
            title=pull.title or "",
            state=pull.state,
            head=pull.head_sha,
            base=pull.base_sha or "",
            coverage=coverage_html,
            patch=patch_html,
        )
    )
