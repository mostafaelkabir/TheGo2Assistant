---
id: T-028
title: Mirror source permissions so a reader sees only files shared with them
status: backlog
phase: 2-gate
priority: P3
blocked_by: [T-027, T-012]
github_issue:
owner:
branch:
pr:
created: 2026-09-16
updated: 2026-09-17
closed:
---

## Problem

Workspace membership (T-027) is the coarsest useful unit: everyone in a
workspace sees every document in it. Inside a company that is wrong for the
common case. A Drive folder synced into the `company` workspace holds HR
files shared with three people and a handbook shared with everyone, and the
index cannot tell them apart -- `documents` records where a file came from
but nothing about who the source lets read it. A reader of the workspace
therefore retrieves passages from files they could not open in Drive, and
the citation hands them a link that Drive will refuse.

## Definition

Delivers:

- The connector contract gains a per-file principal list (emails or group
  ids the source says may read the file), fetched alongside metadata on
  every sync, stored on `documents` with `tenant_id`, and refreshed on
  change events.
- Retrieval filters by the requesting user's identity before ranking:
  a hit the user may not read is never a candidate, so it cannot appear,
  cannot be cited, and cannot count against `sufficient_evidence`.
- A user who was removed from a file in the source loses it on the next
  sync, without re-ingesting the file.

Does not deliver: resolving Google Groups or Microsoft 365 groups to
members (files shared with a group the user is in are visible only once the
group is expanded; that is a follow-up with its own quota concerns),
permission mirroring for local uploads (the uploader's workspace role
governs those), or per-chunk permissions.

## Success metrics

- On a test corpus of 20 files with three distinct sharing sets, each of
  three users sees exactly their set through `search_documents`,
  `fetch_document` and `list_documents`; zero passages cross, asserted by
  test.
- A permission change in the source is reflected within one sync, measured
  by the same test after editing the fixture's principal list.
- Search latency on the `dawan` suite does not regress by more than 10%
  with the filter in the query (measured by `go2 evaluate` timing before
  and after).
- The connector contract test in `tests/test_connector_contract.py` covers
  the new field, so the OneDrive connector (T-024) cannot omit it.

## Test cases

- `test_a_reader_never_retrieves_a_file_not_shared_with_them`
- `test_fetch_document_refuses_an_unshared_file_even_by_id`
- `test_list_documents_hides_unshared_files`
- `test_an_unshared_file_does_not_count_toward_sufficient_evidence`
- `test_a_permission_change_is_applied_on_the_next_sync`
- `test_uploads_fall_back_to_the_workspace_role`
- `test_the_connector_contract_requires_readers`

## Design notes

Filter before rank, not after: post-filtering the top-k leaks the existence
of a document through a shorter result list and wastes the reranker on
passages that will be dropped. The filter is a predicate on `documents`
joined into both halves of the hybrid query, so the invariants "hybrid
search, never vector-only" and "`tenant_id` on every query" hold unchanged.
Google Drive exposes readers through `permissions.list` (200 quota units per
file, well inside the measured budget in `docs/roadmap.md`); Graph exposes
them through `/permissions` on a drive item.

## Work log

- 2026-09-17 — Product review: P2 → P3, for the same reason as T-027 and
  one more: it needs live Drive sync (T-012) to have any permissions to
  mirror, and `drive.file` scope means the user already chose what to
  share. Revisit when a client asks for per-person visibility inside one
  workspace.

- 2026-09-16 — Opened while building T-016, as the second half of "access
  levels": T-027 is who may enter a workspace, this is what they see inside
  it.

## Outcome
