---
id: T-036
title: Test client boundaries through real MCP tools
status: backlog
phase: 2-gate
priority: P1
blocked_by: [T-019]
github_issue:
owner:
branch:
pr:
created: 2026-09-17
updated: 2026-09-17
closed:
---

## Problem

`TestBearerAuth` stubs the search tool; `TestToolsAgainstRealData` calls
tool functions directly. These are useful checks of separate layers, but
they do not prove that authenticated MCP responses preserve tenant
isolation and client redaction together. T-019 covers deployment defaults;
the combined client boundary needs its own regression proof. No leak is
asserted as reproduced by this ticket.

## Definition

Add integration cases that go through `build_http_app` and actual MCP
`tools/call` dispatch to real tool implementations and a real test database.
Use two disposable tenants with distinct synthetic canaries and validated
synthetic PII. Keep tests off customer workspaces and clean fixtures up.

- Test search, list and fetch as the authenticated client. Guessing the
  other tenant's document ID and supplying tenant-like arguments/headers
  cannot switch the process workspace or reveal the other tenant's text
  or metadata. Invalid extra arguments may be rejected or ignored safely.
- Missing/incorrect bearer credentials never execute tools. A valid token
  yields only the configured workspace, including after another request.
- Client redaction covers all returned document-derived strings, including
  metadata/citation labels that may contain PII. Source identity and
  page/section remain usable after masking. Test both search and full fetch;
  inspect list responses too. Personal mode retains its documented behavior.
- Verify captured errors/logs and saved traces do not contain bearer tokens
  or raw synthetic PII for these cases. Report any failure as a concrete
  linked defect; fixing a separate mechanism requires its own ticket.

No new role system, source ACL model, penetration-testing program or live
provider calls. Use deterministic local retrieval fixtures when needed,
but do not replace the auth, scope resolution, database filtering or output
redaction under test. Existing full-suite CI runs these integration cases.

## Success metrics

- Zero foreign-tenant canaries or metadata in every response under test.
- Zero raw protected values in client-mode payloads, logs or saved traces;
  citation document identity and location still match the fixture.
- All cases execute against a database in CI; absent database is BLOCKED
  in QA evidence, not a passing boundary check.
- A deliberately bypassed scope filter or redactor makes its relevant test
  fail in a temporary local mutation check; restore production code afterward.

## Test cases

- `test_real_mcp_auth_rejects_before_tool_execution`
- `test_real_mcp_search_and_list_are_workspace_scoped`
- `test_real_mcp_fetch_foreign_document_returns_no_content`
- `test_real_mcp_arguments_and_headers_cannot_change_workspace`
- `test_real_mcp_client_redacts_text_metadata_and_citation_labels`
- `test_real_mcp_personal_mode_preserves_owner_text`
- `test_real_mcp_errors_logs_and_traces_do_not_leak_secrets`

## Design notes

Extend `tests/test_mcp_server.py` and reuse `tests/test_tenancy.py` and
`tests/test_pii.py` fixtures where possible. T-017 migrates real customer
workspaces and remains a separate demo blocker; this ticket uses disposable
tenants and therefore does not depend on that operational migration.

## Work log

- 2026-09-17 — Added composition-level QA for the client gate, based on
  observed separation of transport and database tests.

## Outcome
