---
id: T-015
title: Deletions must drop their chunks
status: backlog
phase: 1-drive
priority: P2
blocked_by: [T-014]
github_issue: 15
owner:
branch:
pr:
created: 2026-09-03
updated: 2026-09-16
closed:
---

## Problem

`RemoteFile.deleted` exists and nothing consumes it. Without this the index
keeps citing documents the user has deleted. A confident citation to a file
that is gone is worse than no answer, and it is exactly the failure the
citation design exists to prevent.

## Definition

Carry a deletion from the connector through to storage: drop the document
and its chunks, tenant-scoped, idempotently. A deletion carries no MIME
type, so the deletion check runs before any "is this ingestable" filter.

## Success metrics

- A file deleted in Drive is not returned by search after the next sync.
- Deleting one file leaves every other document's chunk count unchanged.

## Test cases

- `test_a_deleted_file_removes_its_chunks`
- `test_a_deleted_file_is_no_longer_searchable` -- the real assertion
- `test_deleting_one_file_leaves_the_rest`
- `test_deletion_is_tenant_scoped`
- `test_a_deletion_for_an_unknown_file_is_not_an_error` -- sync is
  at-least-once

## Design notes

## Work log

- 2026-09-03 — Opened as GitHub issue #15.
- 2026-09-16 — Mirrored into the local backlog.

## Outcome
