---
id: T-017
title: Split local into real per-project workspaces
status: ready
phase: 2-gate
priority: P1
blocked_by: []
github_issue: 17
owner:
branch:
pr:
created: 2026-09-03
updated: 2026-09-16
closed:
---

## Problem

`local` holds 92 HaramBlur, 20 Atmata and 5 test documents in one workspace.
A question about one project retrieves passages from the other today. The
UI label was corrected to say `local` rather than `atmata` precisely because
the isolation does not exist; the honest name is a stopgap, not a fix.

## Definition

Reassign documents by `path` or `source` into new tenants, moving chunks,
traces and jobs with them. A dry run reports the move without writing. Every
table carrying `tenant_id` moves together or the split is inconsistent.

## Success metrics

- `atmata` and `haramblur` exist; `local` is empty or retired.
- Document and chunk counts before equal the sum after: nothing lost,
  nothing duplicated.
- A search in `atmata` returns no HaramBlur passage, asserted the same way
  `tests/test_tenancy.py` asserts isolation.

## Test cases

- `test_documents_move_with_their_chunks`
- `test_a_dry_run_changes_nothing`
- `test_counts_reconcile_before_and_after`
- `test_search_after_split_cannot_cross`
- `test_traces_and_jobs_move_too`

## Design notes

This rewrites ownership of real data. Dry run first, and take a database
dump before the real one.

## Work log

- 2026-09-03 — Opened as GitHub issue #17.
- 2026-09-16 — Mirrored into the local backlog.

## Outcome
