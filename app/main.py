from __future__ import annotations

import secrets
from html import escape
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.dashboard import (
    SESSION_COOKIE,
    authenticate_dashboard_user,
    create_dashboard_session,
    create_dashboard_user,
    create_dashboard_user_session,
    current_actor_label,
    ensure_repository_settings,
    onboard_repository,
    parse_ignore_paths,
    require_dashboard_session,
    require_identity,
    token_for_identity,
    upsert_identity_and_token,
)
from app.db import get_session
from app.models import (
    Commit,
    CoverageReportRow,
    ExternalIdentity,
    PrAnnotation,
    PrFileAnnotation,
    PrFileLineAnnotation,
    PullRequest,
    Repository,
)
from app.providers.base import ProviderRepository
from app.providers.registry import get_provider, provider_keys
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
from app.views.coverage_dashboard import (
    app_page_html,
    percent,
    render_pull_file_page,
    render_pull_files_page,
    render_pull_summary_page,
)

app = FastAPI(title="Coverage Service")
OAUTH_STATE_COOKIE = "covivy_oauth_state"


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
        ".chip.disabled{opacity:.65;background:var(--soft);cursor:not-allowed}"
        ".chip-form{margin:0}.logout-chip{font:inherit;cursor:pointer}"
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


def bool_from_form(value: Optional[str]) -> bool:
    return value in {"1", "true", "yes", "on"}


def dashboard_layout(
    title: str,
    body: str,
    settings: Optional[Settings] = None,
    show_logout: bool = False,
) -> HTMLResponse:
    settings = settings or get_settings()
    provider_chips = ['<a class="nav-chip" href="/dashboard">Repositories</a>']
    if not show_logout:
        if settings.github_oauth_client_id and settings.github_oauth_client_secret:
            provider_chips.append('<a class="nav-chip" href="/auth/github">GitHub login</a>')
        else:
            provider_chips.append('<span class="nav-chip disabled">GitHub login unavailable</span>')
        if settings.gitlab_oauth_client_id and settings.gitlab_oauth_client_secret:
            provider_chips.append('<a class="nav-chip" href="/auth/gitlab">GitLab login</a>')
        else:
            provider_chips.append('<span class="nav-chip disabled">GitLab login unavailable</span>')
    if show_logout:
        provider_chips.append(
            '<form method="post" action="/logout" class="chip-form">'
            '<button class="nav-chip logout-chip" type="submit">Logout</button></form>'
        )
    shell = (
        '<main class="app-shell"><header class="app-header">'
        '<a class="app-brand" href="/dashboard"><span class="app-brand-mark">C</span><span>Covivy</span></a>'
        '<nav class="app-nav">{chips}</nav></header>'
        '<section class="dashboard-hero"><div><p class="eyebrow">Workspace</p>'
        '<h1>{title}</h1><p>Configure repositories, install the GitHub App, and manage coverage gates.</p></div></section>'
        "{body}</main>"
    ).format(title=escape(title), chips="".join(provider_chips), body=body)
    return HTMLResponse(app_page_html(title, shell))


def auth_page(settings: Settings, mode: str = "login", message: str = "") -> HTMLResponse:
    github = (
        '<a class="sso-button" href="/auth/github"><span class="sso-mark">GH</span>'
        "<span>Sign in with GitHub</span></a>"
        if provider_configured("github", settings)
        else '<button class="sso-button" disabled><span class="sso-mark">GH</span><span>GitHub unavailable</span></button>'
    )
    gitlab = (
        '<a class="sso-button" href="/auth/gitlab"><span class="sso-mark">GL</span>'
        "<span>Sign in with GitLab</span></a>"
        if provider_configured("gitlab", settings)
        else '<button class="sso-button" disabled><span class="sso-mark">GL</span><span>GitLab unavailable</span></button>'
    )
    is_register = mode == "register"
    action = "/register" if is_register else "/login"
    title = "Create your account" if is_register else "Log in to your account"
    submit = "Register" if is_register else "Log In"
    switch = (
        'Already have an account? <a href="/">Log in instead</a>'
        if is_register
        else 'Don\'t have an account yet? <a href="/register">Register instead</a>'
    )
    name_field = (
        '<label>Display name<input name="display_name" autocomplete="name"></label>' if is_register else ""
    )
    error = '<div class="auth-error">%s</div>' % escape(message) if message else ""
    body = (
        '<main class="auth-page">'
        '<a class="brand" href="/"><span class="brand-mark">C</span><span>Covivy</span></a>'
        '<section class="trust-panel">'
        '<div class="trust-block"><h2>Coverage intelligence for modern PR workflows</h2>'
        '<p>Diff coverage, project trends, and repository gates for teams shipping through pull requests.</p></div>'
        '<div class="trust-row"><strong>GitHub App integration</strong><span>PR comments, commit status checks, repository onboarding</span></div>'
        '<div class="trust-grid"><div>Python</div><div>TypeScript</div><div>Go</div><div>LCOV</div><div>Coverprofile</div><div>Cobertura</div></div>'
        '<div class="cert-pill"><strong>Semantic diff coverage</strong><span>Ignores blanks, comments, tests, and non-runtime code.</span></div>'
        "</section>"
        '<section class="auth-card"><h1>{title}</h1>{github}{gitlab}'
        '<div class="or"><span></span><strong>OR</strong><span></span></div>{error}'
        '<form method="post" action="{action}" class="auth-form">{name_field}'
        '<label>Username or email address<input name="email" type="email" autocomplete="email" required></label>'
        '<label>Password<input name="password" type="password" autocomplete="current-password" required></label>'
        '<div class="auth-actions"><p>{switch}</p><button type="submit">{submit}</button></div>'
        "</form></section></main>"
    ).format(
        title=escape(title),
        github=github,
        gitlab=gitlab,
        error=error,
        action=action,
        name_field=name_field,
        switch=switch,
        submit=escape(submit),
    )
    return HTMLResponse(auth_page_html(title, body))


def auth_page_html(title: str, body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>" + escape(title) + "</title>"
        "<style>"
        ":root{--bg:#f4f6fb;--card:#fff;--ink:#16143d;--muted:#5e6175;--line:#d8deea;"
        "--green:#2edca8;--pink:#ee2b6c;--soft:#eef1f7}"
        "*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);"
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px}"
        "a{color:var(--pink);font-weight:700;text-decoration:none}.auth-page{min-height:100vh;"
        "display:grid;grid-template-columns:minmax(320px,520px) minmax(380px,620px);gap:44px;"
        "align-items:center;max-width:1260px;margin:0 auto;padding:32px 44px;position:relative}.brand{position:absolute;top:24px;left:44px;"
        "display:flex;align-items:center;gap:12px;color:var(--ink);font-size:34px;font-weight:800}"
        ".brand-mark{width:46px;height:46px;border-radius:12px;background:linear-gradient(135deg,#20dfa2,#8cead5);"
        "display:grid;place-items:center;color:#fff}.trust-panel{max-width:560px;justify-self:end}.trust-block h2{font-size:28px;line-height:1.12;margin:0 0 10px}"
        ".trust-block p{font-size:15px;color:var(--muted);line-height:1.5;margin:0 0 26px}.trust-row{border-top:1px solid var(--line);"
        "border-bottom:1px solid var(--line);padding:18px 0;display:grid;gap:6px;font-size:15px}.trust-row span{color:var(--muted)}"
        ".trust-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;border-bottom:1px solid var(--line);padding:24px 0}"
        ".trust-grid div{font-weight:800;font-size:15px}.cert-pill{margin-top:26px;background:#e7eaf3;border-radius:999px;padding:16px 22px;"
        "display:grid;gap:3px}.cert-pill span{color:var(--muted)}.auth-card{background:var(--card);border-radius:12px;box-shadow:0 2px 10px rgba(20,20,50,.08);"
        "padding:36px 46px;max-width:620px;width:100%}.auth-card h1{text-align:center;font-size:28px;margin:0 0 24px}.sso-button{width:100%;height:50px;border:1px solid var(--line);"
        "border-radius:6px;background:#fff;margin:0 0 14px;display:flex;align-items:center;justify-content:center;gap:14px;color:var(--ink);font-size:16px;font-weight:500}"
        ".sso-button:disabled{opacity:.55;background:var(--soft);cursor:not-allowed}.sso-mark{position:absolute;left:36px;font-weight:800;color:var(--green)}"
        ".sso-button{position:relative}.or{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:12px;margin:26px 0;color:var(--ink)}"
        ".or span{height:1px;background:var(--line)}.auth-form{display:grid;gap:18px}.auth-form label{display:grid;gap:8px;font-size:15px}"
        ".auth-form input{height:50px;border:1px solid #cfd6e6;border-radius:6px;font-size:16px;padding:0 12px;background:#fff}"
        ".auth-actions{border-top:1px solid var(--line);padding-top:22px;display:grid;grid-template-columns:1fr 180px;gap:18px;align-items:center}"
        ".auth-actions p{margin:0;text-align:center;color:#20203f}.auth-actions button{height:64px;border:0;border-radius:10px;background:var(--green);"
        "font-size:17px;font-weight:800;color:var(--ink);cursor:pointer}.auth-error{background:#fff0f4;color:var(--pink);border:1px solid #ffc2d4;"
        "padding:12px;border-radius:6px;margin-bottom:16px}@media(max-width:980px){.auth-page{grid-template-columns:1fr;padding:110px 20px 24px}.trust-panel{justify-self:stretch}.auth-card{padding:32px 24px}.auth-actions{grid-template-columns:1fr}.brand{font-size:32px}}"
        "</style></head><body>" + body + "</body></html>"
    )


def provider_configured(provider_key: str, settings: Settings) -> bool:
    if provider_key == "github":
        return bool(settings.github_oauth_client_id and settings.github_oauth_client_secret)
    if provider_key == "gitlab":
        return bool(settings.gitlab_oauth_client_id and settings.gitlab_oauth_client_secret)
    return False


def provider_label(provider_key: str) -> str:
    return {"github": "GitHub", "gitlab": "GitLab"}.get(provider_key, provider_key)


def login_options_html(settings: Settings) -> str:
    links = []
    messages = []
    if provider_configured("github", settings):
        links.append('<a href="/auth/github">GitHub</a>')
    else:
        messages.append("GitHub OAuth not configured")
    if provider_configured("gitlab", settings):
        links.append('<a href="/auth/gitlab">GitLab</a>')
    else:
        messages.append("GitLab OAuth not configured")
    if links:
        suffix = " %s." % "; ".join(messages) if messages else ""
        return "Login with %s to configure repositories.%s" % (" or ".join(links), suffix)
    return "%s. Set OAuth client id and secret in .env." % "; ".join(messages)


def install_github_app_link(settings: Settings, full_name: str) -> str:
    if settings.github_app_install_url:
        return '<a class="configure-link" href="{url}">Install GitHub App</a>'.format(
            url=escape(settings.github_app_install_url)
        )
    return '<span class="chip disabled">GitHub App install URL not configured</span>'


def repository_configure_action(
    provider_repo: ProviderRepository, repository: Optional[Repository], settings: Settings
) -> str:
    if repository is not None and repository.installation_id:
        return '<a href="/dashboard/repos/{repo_id}/settings">Configured</a>'.format(
            repo_id=repository.id
        )
    if provider_repo.provider == "github":
        if repository is not None:
            return "Waiting for GitHub App installation. " + install_github_app_link(
                settings, provider_repo.full_name
            )
        return (
            '<form method="post" action="/dashboard/onboard">'
            '<input type="hidden" name="provider" value="{provider}">'
            '<input type="hidden" name="provider_repo_id" value="{repo_id}">'
            '<input type="hidden" name="full_name" value="{full_name}">'
            '<input type="hidden" name="default_branch" value="{branch}">'
            '<input type="hidden" name="private" value="{private}">'
            '<button type="submit">Install GitHub App</button></form>'
        ).format(
            provider=escape(provider_repo.provider),
            repo_id=escape(provider_repo.external_id),
            full_name=escape(provider_repo.full_name),
            branch=escape(provider_repo.default_branch),
            private=str(provider_repo.private).lower(),
        )
    return '<span class="chip disabled">Provider setup coming soon</span>'


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
def homepage(settings: Settings = Depends(get_settings)):
    return auth_page(settings, "login")


@app.get("/register", response_class=HTMLResponse)
def register_page(settings: Settings = Depends(get_settings)):
    return auth_page(settings, "register")


@app.post("/register", response_class=HTMLResponse)
def register_user(
    email: str = Form(...),
    password: str = Form(...),
    display_name: Optional[str] = Form(None),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    try:
        user = create_dashboard_user(session, settings, email, password, display_name)
    except ValueError as exc:
        session.rollback()
        return auth_page(settings, "register", str(exc))
    raw_session = create_dashboard_user_session(session, settings, user)
    session.commit()
    response = dashboard_layout(
        "Signed in",
        '<section class="panel">Signed in as <strong>{email}</strong>. '
        '<a href="/dashboard">Open repositories</a>.</section>'.format(email=escape(user.email)),
        settings,
        True,
    )
    response.set_cookie(
        SESSION_COOKIE,
        raw_session,
        httponly=True,
        samesite="lax",
        secure=settings.public_base_url.startswith("https://"),
        max_age=60 * 60 * 24 * 30,
    )
    return response


@app.post("/login", response_class=HTMLResponse)
def login_user(
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    user = authenticate_dashboard_user(session, settings, email, password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid email or password")
    raw_session = create_dashboard_user_session(session, settings, user)
    session.commit()
    response = dashboard_layout(
        "Signed in",
        '<section class="panel">Signed in as <strong>{email}</strong>. '
        '<a href="/dashboard">Open repositories</a>.</section>'.format(email=escape(user.email)),
        settings,
        True,
    )
    response.set_cookie(
        SESSION_COOKIE,
        raw_session,
        httponly=True,
        samesite="lax",
        secure=settings.public_base_url.startswith("https://"),
        max_age=60 * 60 * 24 * 30,
    )
    return response


@app.post("/logout")
def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/auth/{provider_key}")
def start_oauth(provider_key: str, settings: Settings = Depends(get_settings)):
    if provider_key not in provider_keys():
        raise HTTPException(status_code=404, detail="provider not found")
    if not provider_configured(provider_key, settings):
        raise HTTPException(
            status_code=400,
            detail="%s OAuth is not configured" % provider_label(provider_key),
        )
    provider = get_provider(provider_key)
    redirect_uri = "%s/auth/%s/callback" % (settings.public_base_url.rstrip("/"), provider_key)
    state = secrets.token_urlsafe(24)
    response = RedirectResponse(provider.authorization_url(state, redirect_uri))
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        httponly=True,
        samesite="lax",
        secure=settings.public_base_url.startswith("https://"),
        max_age=600,
    )
    return response


@app.get("/auth/{provider_key}/callback", response_class=HTMLResponse)
async def oauth_callback(
    request: Request,
    provider_key: str,
    code: str,
    state: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    if provider_key not in provider_keys():
        raise HTTPException(status_code=404, detail="provider not found")
    if not provider_configured(provider_key, settings):
        raise HTTPException(
            status_code=400,
            detail="%s OAuth is not configured" % provider_label(provider_key),
        )
    if not state or request.cookies.get(OAUTH_STATE_COOKIE) != state:
        raise HTTPException(status_code=400, detail="invalid oauth state")
    provider = get_provider(provider_key)
    redirect_uri = "%s/auth/%s/callback" % (settings.public_base_url.rstrip("/"), provider_key)
    token = await provider.exchange_code(code, redirect_uri)
    user = await provider.current_user(token.access_token)
    identity = upsert_identity_and_token(session, user, token)
    raw_session = create_dashboard_session(session, settings, identity)
    session.commit()
    response = dashboard_layout(
        "Signed in",
        '<section class="panel">Signed in as <strong>{login}</strong> with {provider}. '
        '<a href="/dashboard">Open repositories</a>.</section>'.format(
            login=escape(identity.login), provider=escape(identity.provider)
        ),
        settings,
        True,
    )
    response.set_cookie(
        SESSION_COOKIE,
        raw_session,
        httponly=True,
        samesite="lax",
        secure=settings.public_base_url.startswith("https://"),
        max_age=60 * 60 * 24 * 30,
    )
    response.delete_cookie(OAUTH_STATE_COOKIE)
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def authenticated_dashboard(
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    try:
        session_row = require_dashboard_session(session, settings, request.cookies.get(SESSION_COOKIE))
    except PermissionError:
        return auth_page(settings, "login")
    actor = current_actor_label(session, settings, request.cookies.get(SESSION_COOKIE)) or "user"
    repos = []
    identity = session.get(ExternalIdentity, session_row.identity_id) if session_row.identity_id else None
    if identity is not None:
        token = token_for_identity(session, identity)
        repos = await get_provider(identity.provider).list_repositories(token.access_token)
    onboarded = {
        (repo.provider, repo.provider_repo_id): repo
        for repo in session.scalars(select(Repository)).all()
    }
    rows = []
    for repo in repos:
        existing = onboarded.get((repo.provider, repo.external_id))
        action = repository_configure_action(repo, existing, settings)
        rows.append(
            "<tr><td>{provider}</td><td>{repo}</td><td>{branch}</td><td>{action}</td></tr>".format(
                provider=escape(repo.provider),
                repo=escape(repo.full_name),
                branch=escape(repo.default_branch),
                action=action,
            )
        )
    if identity is None:
        for repository in session.scalars(select(Repository).order_by(Repository.full_name)).all():
            status = (
                '<a href="/dashboard/repos/{repo_id}/settings">Configured</a>'.format(
                    repo_id=repository.id
                )
                if repository.installation_id
                else install_github_app_link(settings, repository.full_name)
            )
            rows.append(
                "<tr><td>{provider}</td><td>{repo}</td><td>{branch}</td><td>{action}</td></tr>".format(
                    provider=escape(repository.provider),
                    repo=escape(repository.full_name),
                    branch=escape(repository.default_branch),
                    action=status,
                )
            )
    body = (
        '<section class="dashboard-card"><h2>Repositories</h2>'
        '<table><tr><th>Provider</th><th>Repository</th><th>Default branch</th><th>Action</th></tr>'
        "{rows}</table></section>"
    ).format(rows="\n".join(rows) or '<tr><td colspan="4">No repositories found.</td></tr>')
    return dashboard_layout("Repositories for %s" % actor, body, settings, True)


@app.post("/dashboard/onboard", response_class=HTMLResponse)
def onboard_dashboard_repo(
    request: Request,
    provider: str = Form(...),
    provider_repo_id: str = Form(...),
    full_name: str = Form(...),
    default_branch: str = Form("main"),
    private: str = Form("false"),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    try:
        require_identity(session, settings, request.cookies.get(SESSION_COOKIE))
    except PermissionError:
        raise HTTPException(status_code=401, detail="dashboard login required")
    owner, name = full_name.rsplit("/", 1)
    repository, token = onboard_repository(
        session,
        settings,
        ProviderRepository(
            provider=provider,
            external_id=provider_repo_id,
            owner=owner,
            name=name,
            full_name=full_name,
            default_branch=default_branch,
            private=private == "true",
        ),
    )
    session.commit()
    token_html = (
        '<p>Upload token: <code>{token}</code></p>'.format(token=escape(token)) if token else ""
    )
    if provider == "github" and repository.installation_id is None:
        return dashboard_layout(
            "Waiting for GitHub App installation",
            '<section class="panel"><h2>Waiting for GitHub App installation</h2>'
            '<p>{repo} is saved, but Covivy is not active until the GitHub App is installed '
            "for this repository.</p>{install}</section>".format(
                repo=escape(repository.full_name),
                install=install_github_app_link(settings, repository.full_name),
            ),
            settings,
            True,
        )
    return dashboard_layout(
        "Repository settings",
        '<section class="panel"><h2>Repository settings</h2>'
        '<p>{repo} is ready.</p>{token}'
        '<p><a href="/dashboard/repos/{repo_id}/settings">Configure repository</a></p></section>'.format(
            repo=escape(repository.full_name), token=token_html, repo_id=repository.id
        ),
        settings,
        True,
    )


@app.get("/dashboard/repos/{repository_id}/settings", response_class=HTMLResponse)
def repository_settings_page(
    request: Request,
    repository_id: int,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    try:
        require_identity(session, settings, request.cookies.get(SESSION_COOKIE))
    except PermissionError:
        raise HTTPException(status_code=401, detail="dashboard login required")
    repository = session.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="repository not found")
    repo_settings = ensure_repository_settings(session, repository, settings)
    session.commit()
    return dashboard_layout(
        "Repository settings",
        '<section class="panel"><h2>Repository settings</h2>'
        '<form method="post">'
        '<label>Patch target <input name="patch_coverage_target" value="{patch}"></label><br>'
        '<label>Project target <input name="project_coverage_target" value="{project}"></label><br>'
        '<label>Ignore paths<br><textarea name="ignore_paths" rows="6">{ignore}</textarea></label><br>'
        '<label><input type="checkbox" name="status_enabled" {status}> Status checks</label><br>'
        '<label><input type="checkbox" name="comment_enabled" {comment}> PR comments</label><br>'
        '<button type="submit">Save</button></form>'
        '<form method="post" action="/dashboard/repos/{repo_id}/rotate-token">'
        '<button type="submit">Rotate upload token</button></form></section>'.format(
            patch=repo_settings.patch_coverage_target,
            project=repo_settings.project_coverage_target,
            ignore=escape("\n".join(repo_settings.ignore_paths or [])),
            status="checked" if repo_settings.status_enabled else "",
            comment="checked" if repo_settings.comment_enabled else "",
            repo_id=repository.id,
        ),
        settings,
        True,
    )


@app.post("/dashboard/repos/{repository_id}/settings", response_class=HTMLResponse)
def update_repository_settings_page(
    request: Request,
    repository_id: int,
    patch_coverage_target: float = Form(...),
    project_coverage_target: float = Form(...),
    ignore_paths: str = Form(""),
    status_enabled: Optional[str] = Form(None),
    comment_enabled: Optional[str] = Form(None),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    try:
        require_identity(session, settings, request.cookies.get(SESSION_COOKIE))
    except PermissionError:
        raise HTTPException(status_code=401, detail="dashboard login required")
    repository = session.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="repository not found")
    repo_settings = ensure_repository_settings(session, repository, settings)
    repo_settings.patch_coverage_target = patch_coverage_target
    repo_settings.project_coverage_target = project_coverage_target
    repo_settings.ignore_paths = parse_ignore_paths(ignore_paths)
    repo_settings.status_enabled = bool_from_form(status_enabled)
    repo_settings.comment_enabled = bool_from_form(comment_enabled)
    session.commit()
    return repository_settings_page(request, repository_id, session, settings)


@app.post("/dashboard/repos/{repository_id}/rotate-token", response_class=HTMLResponse)
def rotate_dashboard_token(
    request: Request,
    repository_id: int,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    try:
        require_identity(session, settings, request.cookies.get(SESSION_COOKIE))
    except PermissionError:
        raise HTTPException(status_code=401, detail="dashboard login required")
    repository = session.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="repository not found")
    token = rotate_repository_upload_token(session, settings, repository.owner, repository.name)
    session.commit()
    return dashboard_layout(
        "Upload token rotated",
        '<section class="panel"><h2>Upload token rotated</h2>'
        '<p>{repo}</p><p><code>{token}</code></p></section>'.format(
            repo=escape(repository.full_name), token=escape(token)
        ),
        settings,
        True,
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
    return HTMLResponse(
        render_pull_summary_page(repository, pull, report, base_report, annotation, target)
    )


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
    file_line_rows: list[tuple[PrFileAnnotation, list[PrFileLineAnnotation]]] = []
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
        for file in file_rows:
            line_rows = session.scalars(
                select(PrFileLineAnnotation)
                .where(PrFileLineAnnotation.file_annotation_id == file.id)
                .order_by(PrFileLineAnnotation.line_number)
            ).all()
            file_line_rows.append((file, line_rows))
    return HTMLResponse(
        render_pull_files_page(
            repository,
            pull,
            report,
            base_report,
            annotation,
            file_line_rows,
            target,
        )
    )


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
    return HTMLResponse(render_pull_file_page(repository, pull, file, line_rows, target))
