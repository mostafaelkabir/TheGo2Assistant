---
id: T-018
title: OCR for scanned documents
status: ready
phase: 2-gate
priority: P1
blocked_by: []
github_issue: 18
owner:
branch:
pr:
created: 2026-09-03
updated: 2026-09-16
closed:
---

## Problem

Two Dawan files are image-only PDFs; `FCI-Corporate-Brochure.pdf` is 6 pages
with no text layer at all. They are marked `pending` rather than silently
empty, which is the right failure, but they are unanswerable. Any client
corpus of scanned invoices or signed contracts hits this immediately.

## Definition

OCR only the pages the extractor already reports in `ocr_pages`; that
decision is made and must not be re-decided. Cache by content hash so a page
is never OCR-ed twice. The backfill runs through the batch API, since nothing
about it is latency-sensitive. OCR text goes through the same chunk and embed
path as native text, with page numbers preserved.

## Success metrics

- `FCI-Corporate-Brochure.pdf` answers a question with a page citation, and
  that question is an eval case in `eval/dawan.yaml`.
- A re-ingest of identical bytes makes zero OCR calls.
- Arabic text survives the round trip.

## Test cases

- `test_only_pages_without_a_text_layer_are_sent`
- `test_a_mixed_document_keeps_its_native_text`
- `test_results_are_cached_by_content_hash`
- `test_page_numbers_survive_ocr`
- `test_a_failed_page_marks_the_document_not_the_batch`
- `test_arabic_text_survives_round_trip`

## Design notes

OCR is egress. Page images must pass through `go2.security.guard.screen`
like every other byte that leaves the machine.

## Work log

- 2026-09-03 — Opened as GitHub issue #18.
- 2026-09-16 — Mirrored into the local backlog.

## Outcome
