---
id: T-016
title: Authentication in front of go2 serve --http
status: done
phase: 2-gate
priority: P0
blocked_by: []
github_issue: 16
owner: claude-fable-5.1
branch: feat/http-auth
pr: https://github.com/mostafaelkabir/TheGo2Assistant/pull/24
created: 2026-09-03
updated: 2026-09-16
closed: 2026-09-16
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
- 2026-09-16 — Bearer middleware, bind check and CLI wiring written with the six
  named tests. Opened T-027 (users and roles) and T-028 (source permissions)
  for what this ticket deliberately leaves out.
- 2026-09-16 — Review found no blockers; two notes fixed. PR opened: https://github.com/mostafaelkabir/TheGo2Assistant/pull/24
- 2026-09-16 — Codex review: `localhost` was exempted by string match; now judged by resolved address. PR #24 merged; ticket closed.

## Outcome

Shipped in PR #24: `GO2_HTTP_TOKEN`, an ASGI bearer-token gate wrapping the
whole Streamable HTTP app (`go2.mcp_server.BearerToken`), a bind check that
refuses any non-loopback interface without a token, and the LibreChat deploy
config passing the token per workspace process. Loopback is judged by the
address a host resolves to, not its name. Only the lifespan scope passes
unauthenticated; a websocket scope is closed.

Success metrics as measured:

- A request without the token gets 401 before any tool runs: asserted by
  `test_a_request_without_a_token_is_rejected` against a stubbed tool that
  records whether it ran (it did not), and the 401 is answered before the
  transport or the Host check see the request.
- `go2 serve --http --host 0.0.0.0` without a token exits 1 naming
  `GO2_HTTP_TOKEN` and the interface: `test_binding_beyond_loopback_without_a_token_refuses_to_start`
  through the Typer runner, with no database needed because the check runs
  before the tenant lookup.
- No trace or log line contains the token: asserted at DEBUG across all
  loggers in-process, on the 401 body, on the 200 body and on what the tool
  received. Uvicorn's access log is outside that test; its default format
  carries no headers.
- Full suite at merge: 379 passed, nothing skipped.

Left out, by design: per-user identity and roles (T-027) and per-file
permissions mirrored from the source (T-028). The token is one trust level
per serving process.
