---
id: T-024
title: OneDrive connector over Graph /delta
status: backlog
phase: 4-second-connector
priority: P3
blocked_by: [T-015]
github_issue:
owner:
branch:
pr:
created: 2026-09-16
updated: 2026-09-16
closed:
---

## Problem

The product promise is OneDrive *and* Google Drive, and only one connector
exists. More importantly, the connector seam has never been exercised by a
second implementation, so nobody knows whether it holds.

## Definition

A `Connector` implementation for OneDrive using Graph `/delta`, passing
`tests/test_connector_contract.py` unchanged, with **zero new ingestion
code**. If ingestion needs a change, the abstraction was wrong; that becomes
a ticket of its own before this one continues.

## Success metrics

- The contract suite passes against the OneDrive connector with no edits to
  the suite.
- `git diff --stat` on `go2/jobs/` and `go2/extraction/` is empty.
- One real OneDrive document is searchable with a citation.

## Test cases

- `tests/test_connector_contract.py` parametrised over both connectors.
- `test_a_delta_link_is_persisted_and_resumed`
- `test_a_removed_item_is_reported_as_deleted`

## Design notes

Blocked by the whole Drive chain because the sync loop, cursor persistence
and deletion handling it needs are built there first.

## Work log

- 2026-09-16 — Opened from the roadmap's Phase 4.

## Outcome
