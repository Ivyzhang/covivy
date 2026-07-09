# covivy

Self-hosted, Python-first coverage service inspired by Codecov.

Built for small teams that want PR coverage feedback from their own infrastructure.

## Local run

### Docker Postgres + local app and worker

Start only PostgreSQL in Docker:

```bash
docker compose up -d postgres
```

Create the local Python environment:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Use `localhost` for `DATABASE_URL` when running the app on the host machine:

```bash
export DATABASE_URL="postgresql+psycopg://app:app@localhost:5432/app"
export STORAGE_ROOT="./storage"
export PUBLIC_BASE_URL="http://localhost:8000"
export GITHUB_WEBHOOK_SECRET="change-me"
export UPLOAD_TOKEN_PEPPER="change-me"
export ADMIN_TOKEN="change-me"
export GITHUB_COMMIT_STATUS_ENABLED="false"
export PATCH_COVERAGE_MINIMUM="0.8"
export DASHBOARD_SESSION_SECRET="change-me"
export GITHUB_OAUTH_CLIENT_ID=""
export GITHUB_OAUTH_CLIENT_SECRET=""
export GITLAB_OAUTH_CLIENT_ID=""
export GITLAB_OAUTH_CLIENT_SECRET=""
export GITLAB_BASE_URL="https://gitlab.com"
```

Run migrations:

```bash
.venv/bin/alembic upgrade head
```

Run the API in one terminal:

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Run the worker in a second terminal with the same environment variables:

```bash
.venv/bin/python -m app.worker
```

Verify:

```bash
curl http://localhost:8000/healthz
```

### Full Docker Compose

```bash
cp .env.example .env
docker compose up --build -d postgres
docker compose run --rm app alembic upgrade head
docker compose up --build app worker
```

The API listens on `http://localhost:8000`.

Without Docker, create a virtual environment and run the app directly against a
PostgreSQL database named in `DATABASE_URL`:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Repository setup

GitHub App installation webhooks create repository rows and an upload token hash.
For local development, create or rotate a token with:

```bash
.venv/bin/python -m scripts.create_repo_token owner/repo
```

or through the API:

```bash
curl -X POST "http://localhost:8000/api/v1/repos/owner/repo/upload-token" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

The raw token is returned once and should be stored in GitHub Actions as
`COVERAGE_UPLOAD_TOKEN`.

## Dashboard login and repository settings

The authenticated dashboard is available at `/dashboard`. It supports GitHub and
GitLab OAuth login, repository onboarding, per-repository patch/project coverage
targets, ignore path storage, status/comment toggles, and upload token rotation.

Create OAuth applications with these callback URLs:

```text
$PUBLIC_BASE_URL/auth/github/callback
$PUBLIC_BASE_URL/auth/gitlab/callback
```

Set `DASHBOARD_SESSION_SECRET` to a stable random value. Set the matching
`GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET`,
`GITLAB_OAUTH_CLIENT_ID`, and `GITLAB_OAUTH_CLIENT_SECRET` values for the
providers you want to enable.

## GitHub Actions upload script

After your test command generates `coverage.xml`, call the shell uploader:

```yaml
- name: Upload coverage to covivy
  if: github.event_name == 'pull_request'
  env:
    COVIVY_BASE_URL: https://your-tunnel-or-domain.example
    COVIVY_UPLOAD_TOKEN: ${{ secrets.COVIVY_UPLOAD_TOKEN }}
  run: ./scripts/upload_coverage_to_covivy.sh --coverage-file coverage.xml
```

The script reads PR metadata from the GitHub Actions event payload:

```text
GITHUB_REPOSITORY
GITHUB_EVENT_NAME
GITHUB_EVENT_PATH
```

For matrix builds, run it from only one job, for example:

```yaml
if: github.event_name == 'pull_request' && matrix.python-version == '3.12'
```

It requires `curl` and `jq`, both available on GitHub-hosted Ubuntu runners.
Use `COVIVY_UPLOAD_TOKEN` for the repository upload token returned by covivy.

You can also use the bundled composite action from another repository:

```yaml
- name: Upload coverage to covivy
  if: github.event_name == 'pull_request'
  uses: Ivyzhang/covivy/upload-action@main
  with:
    token: ${{ secrets.COVIVY_UPLOAD_TOKEN }}
    base-url: ${{ vars.COVIVY_BASE_URL }}
    coverage-file: coverage.xml
    format: cobertura
```

For TypeScript or JavaScript projects, generate LCOV and upload it directly:

```yaml
- run: npm test -- --coverage
- uses: Ivyzhang/covivy/upload-action@main
  with:
    token: ${{ secrets.COVIVY_UPLOAD_TOKEN }}
    base-url: ${{ vars.COVIVY_BASE_URL }}
    coverage-file: coverage/lcov.info
    format: lcov
```

For Go projects, upload the native coverprofile:

```yaml
- run: go test ./... -coverprofile=coverage.out
- uses: Ivyzhang/covivy/upload-action@main
  with:
    token: ${{ secrets.COVIVY_UPLOAD_TOKEN }}
    base-url: ${{ vars.COVIVY_BASE_URL }}
    coverage-file: coverage.out
    format: go-coverprofile
```

## Upload contract

```bash
curl -fS -X POST "http://localhost:8000/api/v1/uploads" \
  -H "Authorization: Bearer $COVERAGE_UPLOAD_TOKEN" \
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

For first-version PR feedback, include `pr_number`, the PR head `commit_sha`,
and `base_sha`. The upload path records PR state even if the PR webhook has not
arrived yet; the worker refreshes PR metadata from GitHub before posting status
and comments.

## Local GitHub App test

After the GitHub App is installed and your tunnel points to the local API:

1. Set the GitHub App webhook URL to:

   ```text
   $PUBLIC_BASE_URL/api/v1/github/webhook
   ```

2. Start the API and worker.

3. Redeliver the GitHub App `installation` webhook if the app was installed
   before the local service was running.

4. Open a test PR in the installed repository.

5. Run a local upload smoke test against the PR head SHA:

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

The script verifies `/healthz`, rotates a repository upload token, uploads a
minimal LCOV report, and waits until the commit coverage API returns parsed
coverage. With the worker running and PR metadata synced, the PR should also get
a stable coverage comment. If `GITHUB_COMMIT_STATUS_ENABLED=true`, it also writes
the `coverage/patch` commit status.

## GitHub App

Set `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY_PATH`, `GITHUB_WEBHOOK_SECRET`,
`PUBLIC_BASE_URL`, and `UPLOAD_TOKEN_PEPPER` in `.env`. The webhook endpoint is:

```text
/api/v1/github/webhook
```

The worker creates or updates a stable PR comment. If
`GITHUB_COMMIT_STATUS_ENABLED=true`, it also posts a `coverage/patch` commit
status.

Set `GITHUB_COMMIT_STATUS_ENABLED=false` to only create or update the PR comment
without writing a commit status.

For comment-only local testing, the GitHub App still needs these repository
permissions:

```text
Contents: Read
Metadata: Read
Pull requests: Read
Issues: Read and write
```

`Issues: Read and write` is required because GitHub PR comments use the issues
comments API. `Commit statuses` is only required when
`GITHUB_COMMIT_STATUS_ENABLED=true`.

## Verification

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/alembic upgrade head --sql
```
