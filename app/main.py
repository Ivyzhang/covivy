from __future__ import annotations

from html import escape
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import (
    Commit,
    CoverageReportRow,
    PrAnnotation,
    PrFileAnnotation,
    PrFileLineAnnotation,
    PullRequest,
    Repository,
)
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


def status_icon(passed: bool) -> str:
    if passed:
        return '<span class="status-pass" style="color: green">✓</span>'
    return '<span class="status-fail" style="color: red">✗</span>'


def trend_icon(current: float, base: Optional[float]) -> str:
    if base is None:
        return ""
    if current >= base:
        return '<span class="trend-up" style="color: green">↑</span>'
    return '<span class="trend-down" style="color: red">↓</span>'


def signed_percent(value: Optional[float]) -> str:
    if value is None:
        return "Base unavailable"
    return "%+.2f%%" % (value * 100)


def page_html(title: str, body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>" + escape(title) + "</title>"
        "<style>"
        ":root{color-scheme:light;--bg:#f6f8fa;--panel:#fff;--text:#1f2328;"
        "--muted:#656d76;--border:#d0d7de;--green:#1a7f37;--red:#cf222e;"
        "--blue:#0969da;--soft:#f6f8fa}"
        "*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);"
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px}"
        "a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}"
        ".coverage-page{max-width:1180px;margin:0 auto;padding:24px}"
        ".topbar{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:18px}"
        ".title-block h1{font-size:24px;line-height:1.25;margin:0 0 8px}.muted{color:var(--muted)}"
        ".chips{display:flex;flex-wrap:wrap;gap:8px}.chip{border:1px solid var(--border);"
        "background:var(--panel);border-radius:999px;padding:5px 9px;color:var(--muted)}"
        ".metric-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:18px 0}"
        ".summary-card{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:14px}"
        ".summary-card .label{color:var(--muted);font-size:12px;text-transform:uppercase;font-weight:700}"
        ".summary-card .value{font-size:24px;font-weight:700;margin-top:8px}.summary-card .sub{margin-top:4px;color:var(--muted)}"
        ".status-pass,.trend-up,.positive{color:var(--green);font-weight:700}.status-fail,.trend-down,.negative{color:var(--red);font-weight:700}"
        ".tabs{display:flex;gap:18px;border-bottom:1px solid var(--border);margin:18px 0}.tab{padding:10px 0;font-weight:600}"
        ".tab.active{border-bottom:3px solid var(--text)}.panel{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:16px}"
        "table{width:100%;border-collapse:collapse;background:var(--panel)}th,td{padding:10px 12px;border-bottom:1px solid var(--border);text-align:left;vertical-align:top}"
        "th{font-size:12px;color:var(--muted);text-transform:uppercase;background:var(--soft)}td.num,th.num{text-align:right}"
        ".changed-files-table td:first-child{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}"
        ".files-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:16px}"
        ".file-line-report{display:grid;grid-template-columns:1fr 1fr;gap:16px}.line-list{margin:0;padding:0;list-style:none}"
        ".line-list li{display:flex;gap:8px;padding:7px 9px;border-bottom:1px solid var(--border);font-family:ui-monospace,SFMono-Regular,Menlo,monospace}"
        ".line-covered .mark{color:var(--green);font-weight:700}.line-missing .mark{color:var(--red);font-weight:700}"
        ".file-diff-report{border:1px solid var(--border);border-radius:8px;overflow:hidden;margin:16px 0;background:var(--panel)}"
        ".file-diff-header{display:grid;grid-template-columns:1fr 90px 110px 110px 90px;gap:12px;align-items:center;padding:12px 14px;border-bottom:1px solid var(--border);background:#fff;font-weight:700}"
        ".file-diff-header .file-name{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.file-diff-header .num{text-align:right}"
        ".diff-hunk{background:#f6f8fa;color:var(--muted);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;padding:5px 10px;border-bottom:1px solid var(--border)}"
        ".diff-line{display:grid;grid-template-columns:72px 28px 1fr;align-items:start;min-height:28px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;border-bottom:1px solid #eef1f4}"
        ".diff-line-number{color:#57606a;text-align:right;padding:5px 10px;border-right:1px solid var(--border);background:#f6f8fa}"
        ".diff-marker{text-align:center;padding:5px 0;color:#57606a}.diff-code{white-space:pre-wrap;padding:5px 10px;overflow-wrap:anywhere}"
        ".diff-line-covered{background:#dafbe1}.diff-line-missing{background:#ffebe9}"
        ".diff-line-covered .diff-marker{color:var(--green);font-weight:700}.diff-line-missing .diff-marker{color:var(--red);font-weight:700}"
        "@media(max-width:760px){.coverage-page{padding:14px}.topbar{display:block}.metric-grid,.files-summary,.file-line-report{grid-template-columns:1fr}table{font-size:13px}}"
        "</style></head><body>" + body + "</body></html>"
    )


def metric_card(label: str, value: str, sub: str = "", class_name: str = "") -> str:
    return (
        '<section class="summary-card {class_name}"><div class="label">{label}</div>'
        '<div class="value">{value}</div><div class="sub">{sub}</div></section>'
    ).format(class_name=class_name, label=escape(label), value=value, sub=sub)


def pr_header(repository: Repository, pull: PullRequest, report: Optional[CoverageReportRow]) -> str:
    return (
        '<header class="topbar"><div class="title-block">'
        '<h1>{repo} · PR #{number}: {title}</h1>'
        '<div class="muted">State: {state}</div></div>'
        '<div class="chips">'
        '<span class="chip">Base commit <code>{base}</code></span>'
        '<span class="chip">PR head commit <code>{head}</code></span>'
        '<span class="chip">Coverage report commit <code>{report_commit}</code></span>'
        "</div></header>"
    ).format(
        repo=escape(repository.full_name),
        number=pull.github_pr_number,
        title=escape(pull.title or ""),
        state=escape(pull.state),
        base=escape(pull.base_sha or ""),
        head=escape(pull.head_sha or ""),
        report_commit=escape(pull.head_sha if report is not None else "No report for current head"),
    )


def summary_metrics_html(
    annotation: Optional[PrAnnotation],
    report: Optional[CoverageReportRow],
    base_report: Optional[CoverageReportRow],
    target: float,
) -> str:
    if report is None:
        return '<div class="panel">No coverage report for head commit yet.</div>'
    patch_value = "No patch data"
    patch_sub = ""
    patch_class = ""
    if annotation is not None:
        patch_passed = annotation.patch_line_rate >= target
        patch_value = "%s %s" % (percent(annotation.patch_line_rate), status_icon(patch_passed))
        patch_sub = "%s / %s changed lines" % (
            annotation.patch_covered_lines,
            annotation.patch_total_lines,
        )
        patch_class = "pass" if patch_passed else "fail"
    project_delta = report.line_rate - base_report.line_rate if base_report is not None else None
    project_delta_class = "positive" if project_delta is not None and project_delta >= 0 else "negative"
    return (
        '<div class="metric-grid">'
        "{patch_card}{project_card}{change_card}"
        "</div>"
    ).format(
        patch_card=metric_card("Covered changed lines", patch_value, patch_sub, patch_class),
        project_card=metric_card(
            "Project coverage",
            "%s %s" % (percent(report.line_rate), trend_icon(report.line_rate, base_report.line_rate if base_report else None)),
            "%s / %s covered lines" % (report.covered_lines, report.total_lines),
        ),
        change_card=metric_card(
            "Coverage change",
            '<span class="{class_name}">{value}</span>'.format(
                class_name=project_delta_class,
                value=escape(signed_percent(project_delta)),
            ),
            "Compared with base report" if base_report is not None else "Base coverage report unavailable",
        ),
    )


def file_diff_anchor(file: PrFileAnnotation) -> str:
    return "file-coverage-%s" % file.id


def file_diff_html(file: PrFileAnnotation, line_rows: list[PrFileLineAnnotation], target: float) -> str:
    missing = file.patch_total_lines - file.patch_covered_lines
    line_parts = []
    for line in line_rows:
        line_parts.append(
            '<div class="diff-line {class_name}">'
            '<div class="diff-line-number">{line_number}</div>'
            '<div class="diff-marker">{mark}</div>'
            '<code class="diff-code">{content}</code></div>'.format(
                class_name="diff-line-covered" if line.covered else "diff-line-missing",
                line_number=line.line_number,
                mark="+" if line.covered else "!",
                content=escape(
                    line.line_content if line.line_content is not None else "Line %s" % line.line_number
                ),
            )
        )
    if not line_parts:
        line_parts.append('<div class="diff-line"><div></div><div></div><code class="diff-code">No changed line coverage available.</code></div>')
    return (
        '<section id="{anchor}" class="file-diff-report">'
        '<h3>{path} line coverage</h3>'
        '<div class="file-diff-header">'
        '<div class="file-name">{path}</div>'
        '<div class="num">{missing}</div>'
        '<div class="num">{patch}</div>'
        '<div class="num">{project}</div>'
        '<div class="num">{change}</div>'
        "</div>"
        '<div class="diff-hunk">Changed lines in this file</div>'
        "{lines}</section>"
    ).format(
        anchor=file_diff_anchor(file),
        path=escape(file.path),
        missing=missing,
        patch=percent(file.patch_line_rate),
        project=percent(file.patch_line_rate),
        change=status_icon(file.patch_line_rate >= target),
        lines="".join(line_parts),
    )


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
    base_report = None
    if pull.base_sha:
        base_report = latest_report_for_commit(session, repository.id, pull.base_sha)
    annotation = None
    if report is not None:
        annotation = session.scalar(
            select(PrAnnotation)
            .where(PrAnnotation.pull_request_id == pull.id, PrAnnotation.report_id == report.id)
            .order_by(PrAnnotation.updated_at.desc())
            .limit(1)
        )
    target = get_settings().patch_coverage_minimum
    coverage_html = summary_metrics_html(annotation, report, base_report, target)
    if report is not None and pull.base_sha and base_report is None:
        coverage_html += '<div class="panel">Base coverage report unavailable for project trend.</div>'
    patch_html = "<p>No patch coverage computed yet.</p>"
    if annotation is not None:
        patch_passed = annotation.patch_line_rate >= target
        base_line_rate = base_report.line_rate if base_report is not None else None
        patch_html = (
            '<section class="panel">'
            "<table><tr><th>Metric</th><th>Covered</th><th>Coverage</th></tr>"
            "<tr><td>Covered changed lines</td><td>{patch_lines}</td><td>{patch} {patch_icon}</td></tr>"
            "<tr><td>Project coverage</td><td>{project_lines}</td><td>{project} {project_icon}</td></tr>"
            "<tr><td>Status</td><td colspan=\"2\">{status}</td></tr></table></section>"
            '<section class="panel"><a class="tab active" href="/repos/{owner}/{repo}/pulls/{number}/files">'
            "Changed file coverage</a></section>"
        ).format(
            owner=owner,
            repo=repo,
            number=number,
            patch=percent(annotation.patch_line_rate),
            patch_icon=status_icon(patch_passed),
            patch_lines="%s / %s" % (annotation.patch_covered_lines, annotation.patch_total_lines),
            project=percent(report.line_rate),
            project_icon=trend_icon(report.line_rate, base_line_rate),
            project_lines="%s / %s" % (report.covered_lines, report.total_lines),
            status=annotation.status,
        )
    body = (
        '<main class="coverage-page">'
        "{header}"
        '<nav class="tabs"><span class="tab active">Summary</span>'
        '<a class="tab" href="/repos/{owner}/{repo}/pulls/{number}/files">Changed files</a></nav>'
        "{coverage}<h2>Coverage report commit</h2>{patch}</main>"
    ).format(
        header=pr_header(repository, pull, report),
        owner=owner,
        repo=repo,
        number=pull.github_pr_number,
        coverage=coverage_html,
        patch=patch_html,
    )
    return HTMLResponse(page_html("PR #%s coverage" % pull.github_pr_number, body))


@app.get("/repos/{owner}/{repo}/pulls/{number}/files", response_class=HTMLResponse)
def pull_file_dashboard(owner: str, repo: str, number: int, session: Session = Depends(get_session)):
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
    target = get_settings().patch_coverage_minimum
    base_report = latest_report_for_commit(session, repository.id, pull.base_sha) if pull.base_sha else None
    summary_html = summary_metrics_html(annotation, report, base_report, target)
    rows = ""
    diff_sections = ""
    file_count = 0
    failing_count = 0
    missing_count = 0
    if annotation is not None:
        file_rows = session.scalars(
            select(PrFileAnnotation)
            .where(PrFileAnnotation.annotation_id == annotation.id)
        ).all()
        file_rows = sorted(
            file_rows,
            key=lambda file: (
                file.patch_line_rate >= target,
                file.patch_line_rate,
                -(file.patch_total_lines - file.patch_covered_lines),
                file.path,
            ),
        )
        row_parts = []
        diff_parts = []
        for file in file_rows:
            file_count += 1
            missing_for_file = file.patch_total_lines - file.patch_covered_lines
            missing_count += missing_for_file
            if file.patch_line_rate < target:
                failing_count += 1
            line_rows = session.scalars(
                select(PrFileLineAnnotation)
                .where(PrFileLineAnnotation.file_annotation_id == file.id)
                .order_by(PrFileLineAnnotation.line_number)
            ).all()
            row_parts.append(
                '<tr><td><a href="#{anchor}">{path}</a></td><td>{lines}</td><td>{coverage} {icon}</td>'
                "<td>{missing}</td><td>{status}</td></tr>".format(
                    anchor=file_diff_anchor(file),
                    path=escape(file.path),
                    lines="%s / %s" % (file.patch_covered_lines, file.patch_total_lines),
                    coverage=percent(file.patch_line_rate),
                    icon=status_icon(file.patch_line_rate >= target),
                    missing=missing_for_file,
                    status="passed" if file.patch_line_rate >= target else "failed",
                )
            )
            diff_parts.append(file_diff_html(file, line_rows, target))
        rows = "\n".join(row_parts)
        diff_sections = "\n".join(diff_parts)
    if not rows:
        rows = '<tr><td colspan="5">No changed file coverage available.</td></tr>'
    passing_count = max(file_count - failing_count, 0)
    files_summary = (
        '<div class="files-summary">'
        "{files}{passing}{failing}{missing}</div>"
    ).format(
        files=metric_card("Files changed", str(file_count)),
        passing=metric_card("Files passing target", str(passing_count), class_name="pass"),
        failing=metric_card("Files failing target", str(failing_count), class_name="fail"),
        missing=metric_card("Total missing changed lines", str(missing_count), class_name="fail"),
    )
    body = (
        '<main class="coverage-page">'
        "{header}"
        '<nav class="tabs"><a class="tab" href="/repos/{owner}/{repo}/pulls/{number}">Summary</a>'
        '<span class="tab active">Changed files</span></nav>'
        "{summary}<section class=\"panel\"><h2>Changed file coverage</h2>{files_summary}"
        '<table class="changed-files-table"><tr><th>File</th><th>Changed lines</th>'
        '<th>Patch coverage</th><th>Missing</th><th>Status</th></tr>{rows}</table></section>'
        '<section class="panel"><h2>File coverage details</h2>{diff_sections}</section>'
        "</main>"
    ).format(
        header=pr_header(repository, pull, report),
        owner=owner,
        repo=repo,
        number=number,
        summary=summary_html,
        files_summary=files_summary,
        rows=rows,
        diff_sections=diff_sections or '<p>No changed file coverage available.</p>',
    )
    return HTMLResponse(page_html("PR #%s changed files" % number, body))


@app.get("/repos/{owner}/{repo}/pulls/{number}/files/{file_path:path}", response_class=HTMLResponse)
def pull_single_file_dashboard(
    owner: str,
    repo: str,
    number: int,
    file_path: str,
    session: Session = Depends(get_session),
):
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
    if annotation is None:
        raise HTTPException(status_code=404, detail="changed file coverage not found")
    file = session.scalar(
        select(PrFileAnnotation).where(
            PrFileAnnotation.annotation_id == annotation.id,
            PrFileAnnotation.path == file_path,
        )
    )
    if file is None:
        raise HTTPException(status_code=404, detail="changed file coverage not found")
    line_rows = session.scalars(
        select(PrFileLineAnnotation)
        .where(PrFileLineAnnotation.file_annotation_id == file.id)
        .order_by(PrFileLineAnnotation.line_number)
    ).all()
    target = get_settings().patch_coverage_minimum
    body = (
        '<main class="coverage-page">'
        "{header}"
        '<nav class="tabs"><a class="tab" href="/repos/{owner}/{repo}/pulls/{number}">Summary</a>'
        '<a class="tab" href="/repos/{owner}/{repo}/pulls/{number}/files">Changed files</a>'
        '<span class="tab active">File view</span></nav>'
        '<section class="panel"><h2>{path} line coverage</h2>'
        '<div class="metric-grid">{metric}</div></section>'
        '<section class="panel">{diff}</section></main>'
    ).format(
        header=pr_header(repository, pull, report),
        owner=owner,
        repo=repo,
        number=number,
        path=escape(file.path),
        metric=metric_card(
            "Patch coverage",
            "%s %s" % (percent(file.patch_line_rate), status_icon(file.patch_line_rate >= target)),
            "%s / %s changed lines" % (file.patch_covered_lines, file.patch_total_lines),
        ),
        diff=file_diff_html(file, line_rows, target),
    )
    return HTMLResponse(page_html("%s coverage" % file.path, body))
