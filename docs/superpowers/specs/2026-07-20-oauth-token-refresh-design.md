# OAuth Token Refresh Design

## Problem

Provider-backed dashboard sessions last 30 days, while OAuth access tokens may expire or be revoked sooner. The dashboard currently sends the stored token without checking its expiry and lets provider 401 responses escape as HTTP 500 errors.

## Design

Each provider exposes a `refresh_access_token` operation. GitLab and GitHub implement their provider-specific refresh request and return the existing `OAuthTokenResult` value object. A dashboard helper checks `expires_at` shortly before an API call, refreshes when necessary, and persists rotated access and refresh tokens.

Repository loading retries once after an unexpected provider 401. This covers revoked or prematurely invalidated access tokens whose stored expiry still appears valid. It never retries general network errors or provider 5xx responses.

When refresh is impossible or rejected, the current `UserSession` is deleted and the dashboard renders the login page with a reauthentication message. Provider authentication failure must not become an internal server error.

## Scope

- Support refresh-token exchange for GitLab and GitHub.
- Refresh known-expired tokens before listing repositories.
- Retry once after a repository-listing 401.
- Invalidate only the current dashboard session when reauthentication is required.
- Preserve the existing behavior for local dashboard users.

## Tests

- Provider tests verify refresh request shape and parsed rotated token metadata.
- Dashboard tests verify proactive refresh and persistence.
- Dashboard tests verify a 401 triggers one refresh and retry.
- Dashboard tests verify unavailable or failed refresh returns a login page and clears the current session.

