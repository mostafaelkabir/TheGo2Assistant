---
id: T-012
title: "go2 sync: drive the connector from the CLI"
status: done
phase: 1-drive
priority: P1
blocked_by: [T-011]
github_issue: 12
owner: Claude (Sonnet 5)
branch: drive/sync-cli
pr: https://github.com/mostafaelkabir/TheGo2Assistant/pull/33
created: 2026-09-03
updated: 2026-09-20
closed: 2026-09-20
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

- 2026-09-20 — Implemented `go2 sync`: resolves the tenant's connection,
  refreshes its credential if expired (re-persisting the new one),
  lists with `cursor=None`, runs each file through `ingest_document`.
  Verified live against the owner's real connected account: correctly
  loaded and used the stored credential, printed "nothing to sync" --
  expected, since `drive.file` without T-013's picker has nothing shared
  with the app yet. All 6 named test cases pass; full suite 467 passed.
  Both retrieval evals matched their baselines (local 16/17 MRR 0.94,
  dawan 19/20 MRR 0.97). Pre-PR review found no blockers; its three notes
  (untested refresh-and-repersist path, two untested `_choose_connection`
  branches, and the `dawan` success metric needing a live run to verify)
  were addressed -- the first two with new tests, the third left to the
  owner as the next manual step. Opened PR #33; in-review.

- 2026-09-20 — PR #33 merged. Owner asked to interact with real Drive data
  next; confirmed live that `drive.file` grants zero files without a
  picker, which is exactly what T-013's own Problem statement already
  said. Closed.

## Outcome

Shipped `go2 sync --source gdrive [--limit N] [--account ...]`: resolves
the tenant's stored connection, refreshes an expired credential silently
and re-persists it, lists with `cursor=None`, runs each file through the
existing `ingest_document` pipeline. `repo.find_connections` is the one
new repository primitive.

Success metrics as measured:

- **A synced document has the same fields as a locally ingested one**:
  met -- same `ingest_document` call, same `Scope`, verified by
  `test_synced_files_go_through_the_same_pipeline` and
  `test_source_is_recorded_as_gdrive`.
- **One real Drive document is searchable in the `dawan` workspace with a
  citation back to it**: **not yet measured**. Verified live against the
  owner's real connected account instead: `go2 sync` correctly loaded and
  refreshed the stored credential and returned zero files, which is
  correct behaviour, not a defect -- `drive.file` scope grants nothing
  until a file is explicitly picked, and there is no picker yet. This
  metric needs T-013 (or a manually-shared file) before it can be
  measured for real, and is why T-013 is next rather than optional.

All 6 named test cases pass, plus 3 more the pre-PR review's notes added
(expired-credential refresh-and-repersist, two `_choose_connection`
branches). Full suite 467 passed, nothing skipped. Both retrieval evals
matched their baselines exactly (local 16/17 MRR 0.94, dawan 19/20 MRR
0.97) -- `find_connections` is additive, as expected.

Left out, as scoped before claiming: persisted cursor between runs
(T-014), removing a deleted file's chunks (T-015), the picker (T-013).
