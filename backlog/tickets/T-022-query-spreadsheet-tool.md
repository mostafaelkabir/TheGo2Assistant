---
id: T-022
title: "query_spreadsheet: answer from the rows, not the summary"
status: ready
phase: 3-accuracy
priority: P2
blocked_by: []
github_issue:
owner:
branch:
pr:
created: 2026-09-16
updated: 2026-09-16
closed:
---

## Problem

Invariant 3 says spreadsheets are never chunked as prose: a per-sheet
summary is indexed and the real table is kept whole, to be served by
`query_spreadsheet`. The summary half exists; the tool does not. Today a
figure inside a sheet is *locatable* (search finds the right sheet) but not
*answerable* (nothing returns the row). "What's the total in the Q3 budget?"
is the third question shape `docs/architecture.md` says agentic search
exists for, and it cannot be answered.

## Definition

A fourth MCP tool that takes a document id, a sheet name and a bounded
selector (a column filter, a row range, or a header lookup) and returns the
matching rows with their coordinates as the citation. Tenant-scoped like the
other three. Row limits bounded so a model cannot pull a whole workbook into
context.

Out of scope: formulas, charts, and cross-sheet joins.

## Success metrics

- At least three eval cases whose answer is a cell value pass with a
  citation naming sheet and row.
- A request for a sheet in another tenant returns nothing.
- Output size is bounded regardless of sheet size.

## Test cases

- `test_rows_are_returned_with_sheet_and_row_citations`
- `test_a_header_lookup_finds_the_column_case_insensitively`
- `test_output_is_capped_at_the_row_limit`
- `test_the_tool_is_tenant_scoped`
- `test_a_missing_sheet_is_reported_not_guessed`

## Design notes

The stored table format already exists from ingestion; this ticket reads it.
If reading it needs a schema change, that is a finding to record here first.

## Work log

- 2026-09-16 — Opened from the roadmap's Phase 3 "remaining work".

## Outcome
