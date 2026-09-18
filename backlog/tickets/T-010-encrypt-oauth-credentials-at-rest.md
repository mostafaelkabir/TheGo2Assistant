---
id: T-010
title: Encrypt OAuth credentials at rest
status: in-progress
phase: 1-drive
priority: P1
blocked_by: []
github_issue: 10
owner: Claude (Opus 4.8)
branch: drive/encrypt-oauth-at-rest
pr:
created: 2026-09-03
updated: 2026-09-18
closed:
---

## Problem

`connections.token_blob` exists as `bytea` and the migration comment already
says "Fernet-encrypted OAuth credentials", but `ensure_connection` writes
`b""` and nothing ever reads it. A refresh token is a long-lived key to
somebody's whole Drive; it must not land in Postgres as plaintext, and the
column is already there waiting.

## Definition

Encrypt and decrypt helpers beside the other security code, so one place
knows the format. Key from config (`GO2_FERNET_KEY`), never from code. An
absent key fails loudly the moment a real token is encrypted or decrypted,
with an actionable message and no plaintext written. `ensure_connection`
stores ciphertext; a loader returns the plaintext to the caller only.

Out of scope: the OAuth flow itself (T-011).

Note on the key name: this ticket originally said `GO2_TOKEN_KEY`, but a
`fernet_key` / `GO2_FERNET_KEY` placeholder was later added to `config.py`
and `.env.example` (unused until now). Using the already-shipped, already
advertised name avoids renaming a secret env var and silently orphaning a
value the owner may already have set. Reconciled to `GO2_FERNET_KEY`.

## Success metrics

- A token survives a process restart.
- `SELECT token_blob` shows ciphertext; the plaintext token is not a
  substring of the stored bytes.
- No test log line contains the token.

## Test cases

- `test_a_token_round_trips` -- encrypt then decrypt returns the original
- `test_the_stored_blob_is_not_the_plaintext`
- `test_a_missing_key_fails_loudly` -- actionable message, no plaintext stored
- `test_a_wrong_key_does_not_silently_return_garbage` -- raises
- `test_tokens_are_never_logged` -- caplog holds no substring of the token

## Design notes

Matches the single-egress-boundary principle: one module knows the format,
so there is one place to audit.

## Work log

- 2026-09-03 — Opened as GitHub issue #10.
- 2026-09-16 — Mirrored into the local backlog.
- 2026-09-18 — Claimed by Claude (Opus 4.8) on branch
  drive/encrypt-oauth-at-rest. Reconciled the key env var to the shipped
  `GO2_FERNET_KEY` placeholder (see Definition note).

## Outcome
