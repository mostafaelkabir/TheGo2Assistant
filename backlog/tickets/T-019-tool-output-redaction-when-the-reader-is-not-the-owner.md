---
id: T-019
title: Turn on tool-output redaction when the reader is not the owner
status: ready
phase: 2-gate
priority: P1
blocked_by: [T-016]
github_issue: 19
owner:
branch:
pr:
created: 2026-09-03
updated: 2026-09-17
closed:
---

## Problem

`screen_tool_output` works and `GO2_PII_REDACT_TOOL_OUTPUT` is honoured, but
nothing decides *when* it should be on. It stays off by default, so a
client-facing deployment silently returns a third party's PII.

## Definition

Redaction follows the deployment, not the request: a serving process either
answers for the data's owner or it does not. A client-facing deployment
defaults to redacting; a personal one still returns plain text. The setting
covers `fetch_document` as well as search results, and citations survive it.

## Success metrics

- A client-facing server redacts without any per-request flag.
- The personal default does not regress: `go2 search` on your own documents
  returns plain text.

## Test cases

- `test_a_client_facing_deployment_defaults_to_redacting`
- `test_a_personal_deployment_still_returns_plain_text`
- `test_the_setting_covers_fetch_document_too`
- `test_citations_survive_redaction`

## Design notes

Depends on T-016 for the notion of a client-facing deployment.

## Work log

- 2026-09-03 — Opened as GitHub issue #19.
- 2026-09-16 — Mirrored into the local backlog.
- 2026-09-17 — T-016 shipped; unblocked and marked ready.

## Outcome
