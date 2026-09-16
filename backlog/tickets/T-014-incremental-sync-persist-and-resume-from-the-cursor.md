---
id: T-014
title: "Incremental sync: persist and resume from the cursor"
status: backlog
phase: 1-drive
priority: P2
blocked_by: [T-012]
github_issue: 14
owner:
branch:
pr:
created: 2026-09-03
updated: 2026-09-16
closed:
---

## Problem

`save_cursor` and `get_cursor` exist and nothing calls them, so every sync
re-enumerates the whole account.

## Definition

Take the cursor **before** listing (the connector already does, and
`tests/test_connector_contract.py::TestResumability` pins it). Persist the
cursor only after the page is durably ingested, or a crash loses files
silently. An invalid cursor falls back to a full sync.

## Success metrics

- A second sync of an unchanged account embeds nothing.
- A sync killed mid-page re-fetches that page on the next run.

## Test cases

- `test_a_second_sync_only_fetches_changes`
- `test_the_cursor_is_persisted_between_runs`
- `test_a_crash_mid_page_does_not_advance_the_cursor` -- at-least-once
- `test_an_invalid_cursor_falls_back_to_a_full_sync`
- `test_unchanged_content_does_not_re_embed` -- content-hash short-circuit

## Design notes

## Work log

- 2026-09-03 — Opened as GitHub issue #14.
- 2026-09-16 — Mirrored into the local backlog.

## Outcome
