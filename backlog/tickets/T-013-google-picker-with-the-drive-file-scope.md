---
id: T-013
title: Google Picker with the drive.file scope
status: backlog
phase: 1-drive
priority: P2
blocked_by: [T-012]
github_issue: 13
owner:
branch:
pr:
created: 2026-09-03
updated: 2026-09-16
closed:
---

## Problem

`drive.file` only grants what the user explicitly picks, so without a picker
there is nothing to sync. This is the piece that turns the tool into
something a client can connect themselves.

## Definition

A minimal local page that hands selected file ids to the connector. The
selection is persisted, and the selection source is kept swappable.

## Success metrics

- A client can pick a folder in a browser and its contents sync, with
  nothing outside the selection visible to `list_documents`.
- The selection survives a restart of the serving process.

## Test cases

- `test_only_picked_files_are_listed`
- `test_a_picked_folder_includes_its_children`
- `test_the_selection_survives_a_restart`
- `test_removing_a_selection_stops_future_syncs` -- without deleting
  already-indexed content absent an explicit purge

## Design notes

## Work log

- 2026-09-03 — Opened as GitHub issue #13.
- 2026-09-16 — Mirrored into the local backlog.

## Outcome
