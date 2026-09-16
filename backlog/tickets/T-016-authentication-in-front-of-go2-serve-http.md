---
id: T-016
title: Authentication in front of go2 serve --http
status: in-progress
phase: 2-gate
priority: P0
blocked_by: []
github_issue: 16
owner: Claude Fable 5.1 (for Mostafa Elkabir)
branch: feat/http-auth
pr:
created: 2026-09-03
updated: 2026-09-16
closed:
---

## Problem

There is **no authentication**. The only thing protecting the entire index is
that the server binds loopback, and the Linux instructions in
`deploy/librechat/README.md` tell you to bind the Docker bridge, at which
point any container on the host can read every document in every workspace.
No client demo on a shared or remote machine can honestly happen before this
exists.

## Definition

A bearer token, constant-time compared and never logged. Auth answers *may
you talk to this server*, not *which workspace*: the tenant is already chosen
by the serving process, and the two must not be conflated. Binding beyond
loopback without a configured token refuses to start.

## Success metrics

- A request without the token gets 401 before any tool runs.
- `go2 serve --http --host 0.0.0.0` without a token exits non-zero with a
  message naming the fix.
- No trace or log line contains the token.

## Test cases

- `test_a_request_without_a_token_is_rejected`
- `test_a_wrong_token_is_rejected`
- `test_a_valid_token_reaches_the_tools`
- `test_the_token_is_compared_in_constant_time`
- `test_the_token_never_appears_in_logs_or_traces`
- `test_binding_beyond_loopback_without_a_token_refuses_to_start`

## Design notes

A gate, not a feature: T-019 and any hosted deployment (T-026) depend on it.

## Work log

- 2026-09-03 — Opened as GitHub issue #16.
- 2026-09-16 — Mirrored into the local backlog.
- 2026-09-16 — Claimed on `feat/http-auth`.

## Outcome
