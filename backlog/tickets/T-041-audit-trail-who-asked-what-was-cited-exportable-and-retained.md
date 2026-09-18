---
id: T-041
title: 'Audit trail: who asked, what was cited, exportable and retained'
status: backlog
phase: 5-on-prem
priority: P3
blocked_by: [T-027]
github_issue:
owner:
branch:
pr:
created: 2026-09-18
updated: 2026-09-18
closed:
---

## Problem

Migration `004` records a trace per request and a row per tool step,
scoped by tenant and deliberately without document text. That is the right
shape for an audit trail and not yet one: there is no user on a trace
(T-027 adds the principal), no retention rule, no export, and no guarantee
a row cannot be edited after the fact. The question a bank's audit
function asks is "who was told what, from which document, when", and today
the answer is `go2 trace` on the developer's terminal, showing the last
ten requests.

## Definition

- The user id from T-027 on every trace made over HTTP; stdio and CLI
  traces record the operator.
- `go2 audit export --workspace W --from DATE --to DATE` writing JSONL
  with, per request: timestamp, user, workspace, the question, each tool
  call with its arguments, the cited document ids and locations, and the
  evidence verdict. Never passage text or document content; the trace
  principle from migration `004` stands.
- A retention setting with a documented default and `go2 audit purge`
  that removes only rows past the horizon and reports what it removed.
- Traces are append-only through the application: no code path updates
  or deletes a trace except the purge, asserted by test.

Does not deliver: capture of the final answer text, which the chat client
composes and the server never sees. The ticket documents how the chat
UI's own logging is configured to keep it, and states that limit plainly
in `docs/on-prem.md` rather than implying the export contains answers.

## Success metrics

- An export of one day reproduces every request in that day with user,
  question and citations, checked against the trace table by test.
- Zero passage text in the export, asserted by a test that plants a
  canary in a document and searches the export for it.
- Purge with a 90-day horizon removes exactly the rows older than 90 days
  and none younger, by test.
- Export of 10,000 traces completes in under ten seconds on the dev
  machine.

## Test cases

- `test_export_contains_user_question_and_citations_for_each_trace`
- `test_export_contains_no_passage_text`
- `test_retention_purge_removes_only_expired_traces`
- `test_traces_cannot_be_updated_or_deleted_through_the_application`
- `test_stdio_traces_record_the_operator`

## Design notes

Builds on `go2.observability` and migration `004`. Append-only at the
database level (revoking UPDATE and DELETE from the application role) is
stronger than a code convention and should be preferred where the
deployment owns the role. Blocked by T-027 because an audit trail with no
user on it is a request log.

## Work log

- 2026-09-18 — Opened from the strategy review: identity and audit share
  one seam, and the trace table was already the right shape.

## Outcome
