---
id: T-011
title: "go2 connect google: the authorisation flow"
status: ready
phase: 1-drive
priority: P1
blocked_by: [T-010]
github_issue: 11
owner:
branch:
pr:
created: 2026-09-03
updated: 2026-09-18
closed:
---

## Problem

Nothing in `go2/` references OAuth. `google-auth-oauthlib` is already
declared; the flow is not written, so the tested connector cannot be
authorised against a real account.

## Definition

Installed-app flow reading `.secrets/google_client_secret.json`. Scope is
**`drive.file`** (see `docs/roadmap.md`: a personal Gmail cannot use the
Internal user type, so `drive.readonly` means either 7-day token expiry or a
CASA audit). Credentials are stored through T-010's encryption, keyed by
`(tenant_id, source, account)`, the existing unique constraint.

## Success metrics

- `go2 connect google` completes and `go2 tenant list` shows a Drive
  connection.
- The connection row holds ciphertext.
- An expired access token refreshes without a re-prompt.

## Test cases

- `test_credentials_are_stored_encrypted`
- `test_connecting_twice_updates_rather_than_duplicates`
- `test_an_expired_access_token_is_refreshed` -- against a fake, no re-prompt
- `test_a_revoked_refresh_token_reports_actionably` -- names the fix
- `test_the_requested_scope_is_drive_file` -- guards against widening it
- `test_connect_is_tenant_scoped`

## Design notes

Blocked by T-010: storing a token before encryption exists would put
plaintext in the database, even briefly.

## Work log

- 2026-09-03 — Opened as GitHub issue #11.
- 2026-09-16 — Mirrored into the local backlog.

- 2026-09-18 — T-010 closed; unblocked, set ready.

## Outcome
