# OAuth Token Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent expired or revoked GitLab and GitHub OAuth tokens from causing a dashboard 500.

**Architecture:** Extend the provider protocol with token refresh, then centralize expiry checks, persistence, one-time 401 recovery, and session invalidation in the dashboard authentication boundary. Provider implementations remain responsible only for their OAuth endpoint details.

**Tech Stack:** Python 3.9, FastAPI, SQLAlchemy, HTTPX, unittest/pytest

---

### Task 1: Provider Refresh Contract

**Files:**
- Modify: `app/providers/base.py`
- Modify: `app/providers/gitlab.py`
- Modify: `app/providers/github.py`
- Test: `tests/test_providers.py`

- [ ] Add provider tests that call `refresh_access_token("old-refresh")`, assert the correct provider OAuth request, and assert returned rotated token values.
- [ ] Run `pytest tests/test_providers.py -q` and confirm failure because the refresh methods do not exist.
- [ ] Add `refresh_access_token(refresh_token: str) -> OAuthTokenResult` to the protocol and both providers. GitLab posts form data with `grant_type=refresh_token`; GitHub posts JSON with `grant_type=refresh_token` and requests JSON responses.
- [ ] Run `pytest tests/test_providers.py -q` and confirm all provider tests pass.

### Task 2: Proactive Dashboard Refresh

**Files:**
- Modify: `app/dashboard.py`
- Modify: `app/main.py`
- Test: `tests/test_dashboard_auth.py`

- [ ] Add a dashboard regression test with an expired stored token and refresh token; assert `/dashboard` succeeds, uses the rotated access token, and persists all rotated token metadata.
- [ ] Run the focused test and confirm it fails because the old access token is used.
- [ ] Add an async dashboard helper that refreshes tokens expiring within one minute, preserves an omitted rotated refresh token, and flushes the updated OAuth row before returning it.
- [ ] Route repository loading through the helper.
- [ ] Run the focused test and then `pytest tests/test_dashboard_auth.py -q`; confirm both pass.

### Task 3: Reactive 401 Recovery and Reauthentication

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_dashboard_auth.py`

- [ ] Add a test where repository listing returns 401 once, refresh succeeds, and the retry succeeds; assert exactly one refresh and two list attempts.
- [ ] Add a test where refresh is unavailable or rejected; assert `/dashboard` returns 200 with a sign-in message and the current `UserSession` is removed.
- [ ] Run both focused tests and confirm they fail with the current unhandled `HTTPStatusError`.
- [ ] Catch only provider 401 responses, attempt at most one refresh, and on authentication failure delete the current session, commit, clear the session cookie, and render the login page.
- [ ] Run `pytest tests/test_dashboard_auth.py -q` and confirm all dashboard authentication tests pass.

### Task 4: Full Verification

**Files:**
- Verify all modified files.

- [ ] Run `pytest -q` and confirm the complete suite has zero failures.
- [ ] Run the repository's configured formatting or lint command if one exists in `pyproject.toml`.
- [ ] Inspect `git diff --check` and `git diff` for whitespace errors, accidental secrets, and unrelated changes.
- [ ] Report the fix against GitHub issue #15, including verification evidence and any residual limitations.

