---
id: T-012
title: "go2 sync: drive the connector from the CLI"
status: backlog
phase: 1-drive
priority: P1
blocked_by: [T-011]
github_issue: 12
owner:
branch:
pr:
created: 2026-09-03
updated: 2026-09-16
closed:
---

## Problem

`go2/connectors/gdrive.py` is orphaned: 282 lines and 23 tests, imported by
nothing. Real Drive documents cannot reach the index.

## Definition

`go2 sync --source gdrive [--limit N]`. Reuses the existing job queue and
`ingest_document`: **no new ingestion path** (invariant 2). Every write goes
through `Scope(tenant_id, connection_id, source)` as local ingestion already
does. This ticket is wiring, not connector logic.

## Success metrics

- One real Drive document is searchable in the `dawan` workspace with a
  citation back to it.
- A synced document has the same fields as a locally ingested one.
- **This is the D0 milestone: stop and use it for a few days before T-013.**

## Test cases

- `test_synced_files_go_through_the_same_pipeline`
- `test_sync_is_scoped_to_the_active_tenant`
- `test_limit_stops_early` -- `--limit 1` fetches exactly one
- `test_an_unsupported_file_is_skipped_not_failed`
- `test_one_bad_file_does_not_abort_the_run`
- `test_source_is_recorded_as_gdrive` -- `list_documents(source="gdrive")`

## Design notes

## Work log

- 2026-09-03 — Opened as GitHub issue #12.
- 2026-09-16 — Mirrored into the local backlog.

## Outcome
