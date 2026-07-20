# Covivy

Self-hosted, PR-first code coverage for teams that want to own their data and quality gates.

## 中文简介

Covivy 是一个面向 Pull Request 的自托管代码覆盖率平台。CI 可以上传 Cobertura、LCOV 或 Go coverprofile 报告；Covivy 会结合 PR diff、源码和语言语义计算增量覆盖率（patch coverage），并通过 GitHub commit status、稳定更新的 PR 评论和文件级可视化页面反馈结果。

项目重点解决整体覆盖率无法准确反映新增代码质量的问题，同时覆盖多语言报告归一化、异步任务处理、webhook/upload 乱序、force-push 后旧报告隔离，以及 Python、JavaScript/TypeScript 多行语句的语义化覆盖判定。

## English Overview

Covivy is a self-hosted, pull-request-first coverage service inspired by Codecov. CI uploads a coverage report, Covivy normalizes it into file- and line-level data, combines it with the current PR diff and source, and publishes patch coverage through a GitHub commit status, an updatable PR comment, and a detailed dashboard.

Unlike project-wide coverage, patch coverage focuses on the code introduced by the current change. This keeps historical coverage from hiding untested new code and makes coverage useful as a PR quality gate.

## Why Covivy

- **PR-first quality feedback**: measure coverable lines changed by the current pull request.
- **Self-hosted data ownership**: keep repository metadata and coverage reports in your environment.
- **Language-independent ingestion**: accept reports produced by Python, JavaScript/TypeScript, and Go toolchains.
- **Actionable results**: show uncovered changed lines instead of only a project-wide percentage.
- **Resilient GitHub integration**: handle upload/webhook ordering and skip stale reports after a force-push.

## Features

- Cobertura XML, LCOV, and Go coverprofile parsing.
- Project, file, line, and PR patch coverage persistence.
- Python AST-aware multiline statement coverage.
- TypeScript compiler-based runtime statement and non-code classification.
- Go coverprofile block expansion and structural-line filtering.
- Test-file, blank-line, comment, and type-only change exclusion from patch coverage.
- PostgreSQL-backed asynchronous jobs with row locking, retries, and exponential backoff.
- GitHub App installation and repository synchronization webhooks.
- Stable PR comments, optional `coverage/patch` commit status, and pending/failure feedback.
- Stale upload protection when the PR head SHA changes.
- File-level changed-line reports with bounded semantic source context.
- Local account login plus GitHub and GitLab OAuth dashboard login.
- Per-repository patch/project target storage, status/comment toggles, ignore-path storage, and upload-token rotation.
- Reusable composite GitHub Action and standalone shell uploader.

## Architecture

```mermaid
flowchart LR
    CI[CI / GitHub Actions] -->|coverage report| API[FastAPI upload API]
    API -->|raw report| FS[File storage]
    API -->|upload, commit, PR, job| DB[(PostgreSQL)]
    DB --> WORKER[Worker]
    FS --> WORKER
    WEBHOOK[GitHub webhooks] -->|installation and PR sync| API
    WORKER -->|PR, diff, source| GH[GitHub API]
    WORKER --> ENGINE[Coverage engine]
    ENGINE -->|report and annotations| DB
    WORKER -->|status and stable comment| GH
    DB --> UI[Coverage dashboard]
```

### End-to-end flow

1. A CI job generates a supported coverage report and uploads it with repository, commit, branch, and PR metadata.
2. The API verifies the repository upload token, stores the raw file, upserts the commit and PR, and enqueues a parse job.
3. The worker claims the job from PostgreSQL, parses the report, and persists normalized file- and line-level coverage.
4. For PR uploads, the worker refreshes the PR from GitHub and verifies that the report commit is still the current head SHA.
5. The worker fetches changed files and source, computes semantic patch coverage, and stores PR/file/line annotations.
6. Covivy updates the existing PR comment, optionally writes the `coverage/patch` commit status, and serves the detailed report from the dashboard.

The upload path is the primary PR coverage path. Webhooks synchronize GitHub App installations, repository membership, and PR state, and compensate when GitHub events and coverage uploads arrive in either order.

## Coverage Model

Covivy normalizes every supported input into the same shape:

```text
CoverageReport
  -> CoveredFile(path)
       -> CoveredLine(number, hits, branch, condition coverage)
```

Patch coverage is calculated from added lines on the PR head side:

```text
patch coverage = covered coverable changed lines / coverable changed lines
```

Path normalization removes common workspace prefixes and supports a unique suffix match when a coverage report path differs from the GitHub path. Ambiguous or unmatched paths are reported as warnings instead of being guessed.

For source-aware analysis:

- Python uses the standard-library AST to associate changed lines with their smallest containing statement.
- JavaScript and TypeScript use the TypeScript compiler API to distinguish runtime coverage units from interfaces, type-only imports/exports, ambient declarations, comments, and blank lines.
- Go expands coverprofile blocks to lines and excludes comments and structural-only brace lines.
- When semantic analysis cannot resolve a valid changed line, the line stays in the denominator rather than being silently treated as covered.

## Supported Formats

| Format | Typical ecosystem | Upload value |
| --- | --- | --- |
| Cobertura XML | Python and other XML-producing tools | `cobertura` |
| LCOV | JavaScript and TypeScript | `lcov` |
| Go coverprofile | `go test -coverprofile` | `go-coverprofile` |

## Tech Stack

- Python 3.10+ and FastAPI
- SQLAlchemy 2 and Alembic
- PostgreSQL 16
- `httpx`, PyJWT, and GitHub App installation tokens
- TypeScript compiler API for JS/TS semantic analysis
- Server-rendered HTML coverage dashboards
- Docker Compose for local deployment
- `unittest`, Coverage.py, and Ruff for verification

## Quick Start

### Prerequisites

- Python 3.10 or newer
- Node.js and npm for JavaScript/TypeScript semantic analysis
- Docker with Docker Compose for the local PostgreSQL service

### Run PostgreSQL with the API and worker locally

```bash
git clone https://github.com/Ivyzhang/covivy.git
cd covivy

docker compose up -d postgres

python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
npm ci

cp .env.example .env
```

When the API and worker run on the host, change `DATABASE_URL` in `.env` from `postgres` to `localhost`:

```dotenv
DATABASE_URL=postgresql+psycopg://app:app@localhost:5432/app
STORAGE_ROOT=./storage
PUBLIC_BASE_URL=http://localhost:8000
GITHUB_COMMIT_STATUS_ENABLED=false
```

Apply migrations:

```bash
.venv/bin/alembic upgrade head
```

Start the API:

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Start the worker in another terminal:

```bash
.venv/bin/python -m app.worker
```

Verify the API:

```bash
curl http://127.0.0.1:8000/healthz
```

The API and dashboard are available at `http://127.0.0.1:8000`.

### Run the application with Docker Compose

```bash
cp .env.example .env
docker compose up --build -d postgres
docker compose run --rm app alembic upgrade head
docker compose up --build -d app worker
```

The API and worker share `./storage` through a bind mount. To enable GitHub App operations in containers, make the private-key file available inside the worker container at the path configured by `GITHUB_APP_PRIVATE_KEY_PATH`.

## Configuration

Environment variables are loaded from `.env`; an existing process environment value takes precedence.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://app:app@localhost:5432/app` | SQLAlchemy PostgreSQL connection URL |
| `STORAGE_ROOT` | `./storage` | Raw coverage upload storage directory |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Public URL used in OAuth callbacks and PR report links |
| `UPLOAD_TOKEN_PEPPER` | `local-dev-pepper` | HMAC secret for repository upload-token hashes |
| `ADMIN_TOKEN` | `local-dev-admin` | Administrative token used to rotate repository upload tokens through the API |
| `PATCH_COVERAGE_MINIMUM` | `0.8` | Default repository patch coverage target |
| `GITHUB_APP_ID` | empty | GitHub App identifier |
| `GITHUB_APP_PRIVATE_KEY_PATH` | empty | Path to the GitHub App private key |
| `GITHUB_WEBHOOK_SECRET` | `local-dev-secret` | Secret used to verify GitHub webhook signatures |
| `GITHUB_COMMIT_STATUS_ENABLED` | `true` | Globally enable or disable commit-status writes |
| `GITHUB_APP_INSTALL_URL` | empty | GitHub App installation URL shown during onboarding |
| `DASHBOARD_SESSION_SECRET` | `local-dashboard-secret` | HMAC secret for dashboard sessions and local credentials |
| `GITHUB_OAUTH_CLIENT_ID` | empty | GitHub OAuth application client ID |
| `GITHUB_OAUTH_CLIENT_SECRET` | empty | GitHub OAuth application client secret |
| `GITLAB_OAUTH_CLIENT_ID` | empty | GitLab OAuth application client ID |
| `GITLAB_OAUTH_CLIENT_SECRET` | empty | GitLab OAuth application client secret |
| `GITLAB_BASE_URL` | `https://gitlab.com` | GitLab or self-managed GitLab base URL |

Use unique secrets outside local development. `ADMIN_TOKEN`, the repository upload token, the webhook secret, and the dashboard session secret have different purposes and are not interchangeable.

## GitHub App Setup

Create a GitHub App and configure its webhook URL:

```text
$PUBLIC_BASE_URL/api/v1/github/webhook
```

Set the same webhook secret in GitHub and `GITHUB_WEBHOOK_SECRET`, then configure:

```dotenv
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY_PATH=/absolute/path/to/github-app.private-key.pem
GITHUB_WEBHOOK_SECRET=replace-with-a-random-secret
PUBLIC_BASE_URL=https://coverage.example.com
UPLOAD_TOKEN_PEPPER=replace-with-a-random-secret
```

Recommended repository permissions:

| Permission | Access | Used for |
| --- | --- | --- |
| Contents | Read | Fetch source at the PR head SHA |
| Metadata | Read | Repository metadata |
| Pull requests | Read | Current PR state and changed files |
| Issues | Read and write | Create or update PR comments |
| Commit statuses | Read and write | Write `coverage/patch` when enabled |

Subscribe to these events:

- Installation
- Installation repositories
- Pull request
- Push, if default-branch commit synchronization is needed

For local development, expose port 8000 through an HTTPS tunnel and use that public URL as `PUBLIC_BASE_URL`. After changing secrets or App settings, restart the API and worker, then redeliver the relevant webhook from GitHub.

## Dashboard And Repository Setup

The dashboard is available at `/dashboard`. Users can register a local account or sign in through a configured OAuth provider.

OAuth callback URLs are:

```text
$PUBLIC_BASE_URL/auth/github/callback
$PUBLIC_BASE_URL/auth/gitlab/callback
```

The dashboard supports repository discovery and onboarding, patch/project target configuration, ignore-path storage, commit-status and comment toggles, and upload-token rotation. GitHub repositories need a GitHub App installation before the complete PR feedback path can run.

GitLab OAuth, repository discovery, and provider API primitives are present, but the asynchronous coverage feedback pipeline is currently GitHub-first. Do not treat the current GitLab support as a complete end-to-end merge-request integration.

## Repository Upload Token

Each repository has its own `cov_...` upload token. Only its HMAC hash is stored, and the raw value is returned when the token is created or rotated.

Create or rotate it locally:

```bash
.venv/bin/python -m scripts.create_repo_token owner/repo
```

Or rotate it through the administrative API:

```bash
curl -fS -X POST "http://127.0.0.1:8000/api/v1/repos/owner/repo/upload-token" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Store the returned `cov_...` value as the repository's `COVIVY_UPLOAD_TOKEN` CI secret. The `ADMIN_TOKEN` authorizes token rotation; it must not be used to upload coverage.

## GitHub Actions Integration

### Composite action

Generate coverage in the test job, then invoke the bundled action:

```yaml
- name: Upload coverage to Covivy
  if: github.event_name == 'pull_request'
  uses: Ivyzhang/covivy/upload-action@main
  with:
    token: ${{ secrets.COVIVY_UPLOAD_TOKEN }}
    base-url: ${{ vars.COVIVY_BASE_URL }}
    coverage-file: coverage.xml
    format: cobertura
```

For JavaScript or TypeScript:

```yaml
- run: npm test -- --coverage
- uses: Ivyzhang/covivy/upload-action@main
  with:
    token: ${{ secrets.COVIVY_UPLOAD_TOKEN }}
    base-url: ${{ vars.COVIVY_BASE_URL }}
    coverage-file: coverage/lcov.info
    format: lcov
```

For Go:

```yaml
- run: go test ./... -coverprofile=coverage.out
- uses: Ivyzhang/covivy/upload-action@main
  with:
    token: ${{ secrets.COVIVY_UPLOAD_TOKEN }}
    base-url: ${{ vars.COVIVY_BASE_URL }}
    coverage-file: coverage.out
    format: go-coverprofile
```

The uploader reads `GITHUB_REPOSITORY`, `GITHUB_EVENT_NAME`, and `GITHUB_EVENT_PATH`. On `pull_request`, it resolves the PR number, head SHA and branch, and base SHA and branch from the event payload. For a matrix build, upload from only one job to avoid duplicate reports.

### Standalone uploader

The shell uploader can also run directly from a checked-out Covivy repository:

```yaml
- name: Upload coverage to Covivy
  if: github.event_name == 'pull_request'
  env:
    COVIVY_BASE_URL: ${{ vars.COVIVY_BASE_URL }}
    COVIVY_UPLOAD_TOKEN: ${{ secrets.COVIVY_UPLOAD_TOKEN }}
  run: ./scripts/upload_coverage_to_covivy.sh --coverage-file coverage.xml --format cobertura
```

The script requires `curl` and `jq`.

## Direct Upload API

Coverage files are uploaded as multipart form data:

```bash
curl -fS -X POST "http://127.0.0.1:8000/api/v1/uploads" \
  -H "Authorization: Bearer $COVIVY_UPLOAD_TOKEN" \
  -F "repository=owner/repo" \
  -F "commit_sha=$(git rev-parse HEAD)" \
  -F "branch=$(git branch --show-current)" \
  -F "base_sha=<pr-base-sha>" \
  -F "base_branch=main" \
  -F "pr_number=<pr-number>" \
  -F "format=cobertura" \
  -F "uploader=local" \
  -F "file=@coverage.xml"
```

For PR feedback, send the PR head commit as `commit_sha` and include `pr_number` and `base_sha`. This lets the upload path create or update the PR record even when the webhook has not arrived yet.

## Local End-to-End Verification

With PostgreSQL, the API, and the worker running, use the smoke-test helper:

```bash
.venv/bin/python -m scripts.local_e2e_upload \
  --base-url "$PUBLIC_BASE_URL" \
  --repository owner/repo \
  --commit-sha <pr-head-sha> \
  --branch <pr-branch> \
  --parent-sha <pr-base-sha> \
  --pr-number <pr-number> \
  --admin-token "$ADMIN_TOKEN"
```

The helper checks `/healthz`, rotates the repository upload token, uploads a minimal LCOV report, and polls the commit coverage API until the report is processed. With a configured GitHub App, the PR should also receive an updated coverage comment and, when enabled, a commit status.

Useful read APIs:

| Endpoint | Purpose |
| --- | --- |
| `GET /healthz` | Service health |
| `GET /api/v1/repos/{owner}/{repo}` | Repository metadata |
| `GET /api/v1/repos/{owner}/{repo}/commits/{sha}` | Commit coverage report |
| `GET /api/v1/repos/{owner}/{repo}/pulls/{number}` | PR metadata and current project coverage |
| `GET /repos/{owner}/{repo}/pulls/{number}` | PR coverage dashboard |
| `GET /repos/{owner}/{repo}/pulls/{number}/files` | Changed-file coverage list |

## Development And Verification

Install development dependencies:

```bash
.venv/bin/pip install -r requirements-dev.txt
npm ci
```

Run lint and tests:

```bash
.venv/bin/ruff check app tests scripts alembic
.venv/bin/python -m unittest discover -s tests
```

Check the migration SQL without applying it:

```bash
.venv/bin/alembic upgrade head --sql
```

The test suite covers format parsing, semantic patch coverage, upload and webhook APIs, worker state transitions, GitHub pagination and comment reuse, OAuth/provider behavior, dashboard authentication and settings, and uploader scripts.

## Project Structure

```text
app/
  main.py                         FastAPI routes and server-rendered pages
  coverage.py                     Parsers and patch coverage engine
  services.py                     Upload, report, job, and GitHub workflows
  worker.py                       PostgreSQL job consumer
  models.py                       SQLAlchemy domain and persistence models
  github.py                       GitHub App and installation API clients
  dashboard.py                    Sessions, OAuth identities, and onboarding
  providers/                      GitHub and GitLab provider abstraction
  views/coverage_dashboard.py     PR summary and changed-file report views
alembic/                          Database migrations
scripts/                          Uploaders, smoke test, and TS analyzer
upload-action/                    Composite GitHub Action
tests/                            Unit and integration-style tests
```

## Design Decisions

- **Upload-first PR metadata** avoids making webhook delivery a prerequisite for CI feedback.
- **Database-backed jobs** keep the first deployment small and transactional without requiring Redis or RabbitMQ.
- **Normalized line persistence** makes file-level drill-down and later recalculation possible at the cost of additional storage.
- **Source-aware coverage** reduces false negatives for multiline statements and false positives from type-only or comment changes.
- **Stable comments** keep PR discussions readable while still updating coverage after every upload.

## Current Limitations

- Raw reports use local/shared filesystem storage rather than object storage.
- The PostgreSQL queue does not yet reclaim workers left permanently in `running` after a process crash.
- Large PRs can require many GitHub source requests, and GitHub may omit patches for some large or binary files.
- OAuth access tokens are stored in the database without application-level encryption.
- Local-password hashing is intended for development and should be replaced with a password-specific KDF before production use.
- Private-repository report pages need stricter repository-level authorization for a production multi-tenant deployment.
- Stored ignore paths and the project coverage target are configurable but are not yet applied as active coverage gates.
- GitLab provider primitives are implemented, but the worker feedback pipeline remains GitHub-specific.

## Roadmap

- Apply repository ignore rules and a separate project coverage gate.
- Complete GitLab merge-request upload, worker, status, and comment integration.
- Add object storage, upload size limits, retention policies, and report cleanup.
- Add job leases, stale-lock recovery, dead-letter handling, and operational metrics.
- Support idempotent upload keys and matrix/parallel report merging.
- Handle large diffs by fetching base/head content and computing a fallback diff.
- Encrypt provider tokens and strengthen private-repository authorization.

## License

No license file is currently included. Add an explicit license before distributing Covivy as an open-source project.
