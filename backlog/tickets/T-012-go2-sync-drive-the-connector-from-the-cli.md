---
id: T-012
title: "go2 sync: drive the connector from the CLI"
status: in-progress
phase: 1-drive
priority: P1
blocked_by: [T-011]
github_issue: 12
owner: Claude (Sonnet 5)
branch: drive/sync-cli
pr:
created: 2026-09-03
updated: 2026-09-20
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

Each run lists changes from `cursor=None` -- a full listing every time.
Already-ingested files short-circuit on their content hash the same way a
second `go2 ingest` of an unchanged local file does, so a repeat run is
cheap even without a persisted cursor. A deleted remote file
(`RemoteFile.deleted`) is skipped, not removed from the index -- dropping
its chunks is T-015.

Does not deliver: persisting `save_cursor`/`get_cursor` between runs so a
sync only fetches changes since the last one (T-014); removing a deleted
file's chunks from the index (T-015); the Drive folder/file picker (T-013).
Until T-013 lands, `drive.file` scope means the connector only sees files
the authorized account has explicitly opened with this app or shared with
it -- there is no picker yet to grant broader access, so a fresh connection
with nothing manually shared will legitimately list zero files. That is
worth surfacing to whoever runs this, not a bug to chase.

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

- 2026-09-20 — T-011 closed; unblocked. Tightened the Definition to name
  what is out of scope (cursor persistence is T-014, deletions are T-015,
  the picker is T-013) before claiming, per the ticket workflow. Claimed
  by Claude (Sonnet 5) on `drive/sync-cli` -- the owner connected a real
  Google account with T-011 and wants to search real Drive files next.

## Outcome
