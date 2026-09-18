---
id: T-035
title: Verify the first live Google Drive user journey
status: backlog
phase: 1-drive
priority: P1
blocked_by: [T-012]
github_issue:
owner:
branch:
pr:
created: 2026-09-17
updated: 2026-09-17
closed:
---

## Problem

T-012 requires one searchable real Drive document and then a few days of
use, but has no repeatable account-to-answer acceptance record. Connector
unit tests alone cannot establish that OAuth scope, granted files, refresh,
sync, citation and the actual MCP client work together. This journey is
unverified until the Drive implementation and live account are available.

## Definition

Deliver `docs/qa/drive-d0.md`, an automated synthetic integration smoke
where practical, and a recorded live D0 run using a dedicated test account
or an explicitly granted test folder. Exercise the actual CLI and intended
MCP client, not direct repository calls alone.

- Connect using the scope implemented by T-011; record how each test file
  was granted access before Picker exists. Do not assume selecting a folder
  grants all descendants. If the core journey cannot reach existing files
  with the intended scope, record the blocker and make T-013 a dependency;
  do not silently broaden scope or substitute a local upload.
- Sync a PDF and a native Google document with known synthetic facts into
  an isolated workspace. Answer three questions with correct source and
  page/section citations, including an exact identifier. Ask one question
  absent from the files and verify refusal in the final client answer.
- Restart the process and repeat a query and authenticated sync. Exercise
  token refresh with deterministic tests; confirm a later live sync uses
  the persisted connection without a new consent flow while it is valid.
- Record denied consent, revoked credentials and an ungranted file as
  explicit errors/exclusions rather than successful empty syncs. Confirm
  another workspace cannot list, search or fetch the test documents.

Implementation of OAuth and sync belongs to T-010–T-012. This ticket is
acceptance and missing integration coverage, not a second connector. New
product defects get linked blocking tickets. Incremental updates and
deletions are measured in T-037 after T-014/T-015, not claimed at D0.

## Success metrics

- Both source formats ingested through the shared pipeline; 3/3 supported
  questions correct with verifiable citations; 1/1 unsupported refused.
- Zero cross-workspace results and zero credential values in evidence.
- Restart/reuse and all negative cases recorded with actual observations.
- Record connect-to-first-cited-answer time; proposed D0 target is at most
  30 minutes once dependencies and OAuth application setup are available.
- No live account/access means BLOCKED, never a mocked live acceptance pass.

## Test cases

- `drive_d0_native_and_pdf_to_cited_answer` — live manual acceptance.
- `drive_d0_unknown_answer_is_refused` — final client answer, not rank alone.
- `drive_d0_restart_reuses_connection` — live manual acceptance.
- `test_expired_access_token_refreshes_from_persisted_credentials`
- `test_denied_consent_and_revoked_credentials_are_actionable`
- `drive_d0_ungranted_file_is_not_indexed` — live scope acceptance.
- `drive_d0_second_workspace_cannot_read_first_workspace_files`

## Design notes

Use T-012's source provenance and T-010's ciphertext assertions as supporting
evidence. Tests with fake provider responses stay offline in CI; a live
account is an explicit operator step. Claude prepares everything possible
before handing that step to the account owner.

## Work log

- 2026-09-17 — Added a measurable D0 acceptance step between implementation
  and the existing Dawan rehearsal; no duplicate OAuth/sync implementation.

## Outcome
