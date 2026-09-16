---
id: T-027
title: 'Users and workspace roles: resolve the tenant from the principal'
status: backlog
phase: 2-gate
priority: P1
blocked_by: [T-016, T-017]
github_issue:
owner:
branch:
pr:
created: 2026-09-16
updated: 2026-09-16
closed:
---

## Problem

After T-016 there is one token per serving process, and the process chooses
the tenant. That gives exactly one trust level: whoever holds the token reads
everything in that workspace, and serving a second workspace means a second
process on a second port (`deploy/librechat/README.md` runs two today). A
company knowledge base has many readers with different rights -- a client
who may read their own project's documents, an employee who may read several,
an administrator who may add and remove documents -- and nothing here can
tell them apart. `go2.tenancy` says the tenant will come "from the
authenticated principal" when there are several operators; there is no
principal yet.

## Definition

Delivers:

- `users` and `memberships` tables (both carrying `tenant_id` where they
  scope to a workspace), a membership having one of three roles: `reader`
  (search, fetch, list), `editor` (reader plus ingest and delete documents),
  `admin` (editor plus manage memberships).
- Per-user bearer tokens, stored hashed, issued and revoked from the CLI
  (`go2 user create`, `go2 user token`, `go2 user revoke`).
- One `go2 serve --http` process serving every workspace: the tenant is
  resolved from the authenticated user and a workspace the request names,
  and a user who is not a member of that workspace gets 403 before any tool
  runs. `Scope` is built from the request, not from `GO2_TENANT`.
- Every tool call recorded with the user id in its trace.

Does not deliver: SSO or OIDC (a later ticket, once there is an identity
provider to talk to), document-level permissions inside a workspace
(T-028), a browser UI for managing users, or rate limiting.

## Success metrics

- One server process answers for two workspaces; `tests/test_tenancy.py`
  style isolation holds: a reader of `atmata` cannot retrieve, fetch or list
  any `haramblur` document through any tool, asserted by test.
- A `reader` token calling an editor-only operation gets 403 and the
  operation did not happen (document count unchanged).
- A revoked token is refused on the next request, with no restart.
- `go2 trace` shows the user id on every tool call made over HTTP.
- The single-operator path does not regress: stdio `go2 serve` and the CLI
  still work with `GO2_TENANT` and no users table rows.

## Test cases

- `test_a_user_outside_the_workspace_is_refused_before_any_tool_runs`
- `test_a_reader_cannot_ingest_or_delete`
- `test_an_editor_can_ingest_but_not_manage_memberships`
- `test_a_revoked_token_is_refused_without_a_restart`
- `test_one_process_serves_two_workspaces_in_isolation`
- `test_the_trace_records_the_user`
- `test_stdio_and_the_cli_still_resolve_the_tenant_from_config`

## Design notes

Builds on T-016: the static process token stays as the single-operator path
and the middleware seam (`BearerToken`) is where per-user lookup goes. Auth
(who are you) and authorisation (which workspace, what role) remain separate
steps, in that order. Tokens are stored as sha256 digests and compared in
constant time, as T-016 does. Which workspace a request means: an MCP client
cannot add a path segment per conversation easily, so prefer a header or
mounting `/mcp/<workspace>` per workspace and validating membership there.
Decide with the LibreChat config in hand.

## Work log

- 2026-09-16 — Opened while building T-016, which deliberately stops at
  "may you talk to this server".

## Outcome
