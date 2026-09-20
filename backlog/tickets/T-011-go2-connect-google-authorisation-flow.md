---
id: T-011
title: "go2 connect google: the authorisation flow"
status: done
phase: 1-drive
priority: P1
blocked_by: [T-010]
github_issue: 11
owner: Claude (Sonnet 5)
branch: drive/google-oauth-connect
pr: https://github.com/mostafaelkabir/TheGo2Assistant/pull/32
created: 2026-09-03
updated: 2026-09-20
closed: 2026-09-20
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

- 2026-09-20 — Claimed by Claude (Sonnet 5) on `drive/google-oauth-connect`,
  picked as the top of the roadmap's unclaimed "Now" chain (T-010 → T-012).

- 2026-09-20 — Implemented: `go2/connectors/google_auth.py` (installed-app
  flow, `SCOPES` pinned to `drive.file`, `ensure_fresh` for silent refresh,
  `RevokedCredentialError` naming the fix, `account_email` via `about.get`
  since `drive.file` carries no identity scope); `repo.upsert_connection_token`
  for create-or-reauthorize (distinct from `ensure_connection`, which must
  never clobber a stored token on the upload path); `go2 connect google` CLI
  command; `tenant list` now shows each workspace's non-upload connections.
  All 6 named test cases pass; full suite 455 passed (444 + 11 new), local
  providers, `HF_HUB_OFFLINE=1`. Toolchain clean. Corrected a stale
  `.env.example` comment that still said the consent screen needed
  Internal/Testing for `drive.readonly` -- the ticket's own decision is
  `drive.file`, which does not.

- 2026-09-20 — Pre-PR gate: toolchain clean, full suite 457 passed nothing
  skipped, both retrieval evals matched their baselines exactly (local
  16/17 MRR 0.94, dawan 19/20 MRR 0.97 -- repository.py's new function is
  additive). Independent review found no blockers and two notes, both
  fixed: deduplicated the `SOURCE` constant against `gdrive.py`, and
  wrapped the flow's real failure modes (consent denied, exchange
  rejected, loopback timeout) in `AuthorizationFailedError` instead of
  letting a raw traceback reach the terminal. Opened PR #32; in-review.

- 2026-09-20 — PR #32 merged. Owner ran `go2 connect google` against a real
  Google account on the OAuth consent screen: hit the expected "unverified
  app" Testing-mode block (added as a test user to clear it), then
  completed the flow. `go2 tenant list` showed `connected:
  gdrive:melkabir91@gmail.com` under `local`. Closed.

## Outcome

Shipped `go2/connectors/google_auth.py` (installed-app OAuth flow pinned to
`drive.file`, `ensure_fresh` for a silent refresh, `RevokedCredentialError`
and `AuthorizationFailedError` naming the fix instead of a raw traceback,
`account_email` via `about.get` since `drive.file` carries no identity
scope), `repo.upsert_connection_token` (create-or-reauthorize, distinct
from `ensure_connection`'s never-clobber contract), the `go2 connect
google` CLI command, and a `tenant list` connections line.

Success metrics as measured:

- **`go2 connect google` completes and `go2 tenant list` shows a Drive
  connection**: met, and verified twice over -- once in the test suite
  against stubbed flow functions, and once for real by the owner against
  Google's live OAuth servers with a real Gmail account. `tenant list`
  printed `connected: gdrive:melkabir91@gmail.com`.
- **The connection row holds ciphertext**: met, `test_credentials_are_stored_encrypted`.
- **An expired access token refreshes without a re-prompt**: met for the
  primitive (`ensure_fresh`, unit-tested against a fake credential) -- not
  yet exercised against a real expired Google token, since nothing calls
  it on a live credential until T-012's sync loop does.

All 6 named test cases pass. Full suite 457 passed, nothing skipped
(local providers, `HF_HUB_OFFLINE=1`, Postgres on 5433). Both retrieval
evals matched their baselines exactly (`local` 16/17 MRR 0.94, `dawan`
19/20 MRR 0.97) -- `repository.py`'s new function is additive, as
expected. Independent pre-PR review found no blockers; its two notes
(a duplicated `SOURCE` constant, an unwrapped third-party exception on
consent denial) were fixed before merge.

Left out, as scoped: `go2 sync` (T-012) and the folder/file picker
(T-013). The connector now sits authorized with nothing yet pulling
documents through it -- that is exactly what T-012 is for, and it is
now unblocked.
