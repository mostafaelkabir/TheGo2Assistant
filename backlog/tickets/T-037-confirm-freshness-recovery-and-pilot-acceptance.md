---
id: T-037
title: Confirm freshness, recovery and pilot acceptance
status: backlog
phase: 2-gate
priority: P2
blocked_by: [T-030, T-014, T-015, T-031, T-033]
github_issue:
owner:
branch:
pr:
created: 2026-09-17
updated: 2026-09-17
closed:
---

## Problem

T-030 demonstrates ten known questions once. It does not prove the index
stays current when Drive changes, recovery works after an interruption, or
the intended reader succeeds over repeated use. T-014/T-015 provide the
mechanisms but there is no integrated pilot acceptance record. A successful
demo must not be presented as approval for ongoing client use.

## Definition

Deliver `docs/qa/pilot-acceptance.md` and measured evidence for a small,
single-workspace, single-reader-group pilot. Claude prepares fixtures,
automation and the runbook; the product owner names the actual reader and
performs/reviews the live acceptance. Do not fabricate user feedback.

- Create, edit and delete granted synthetic Drive files; after each
  successful sync verify the current fact is answerable and obsolete/deleted
  content is absent from search, list and direct fetch. Repeating an
  unchanged sync adds no duplicate documents/chunks or embedding work.
- Interrupt a sync between fetch and durable ingestion, then resume. Inject
  a provider timeout and one malformed document. Reconcile all fixture IDs
  to indexed, intentionally excluded or visibly failed states; no silent
  loss or permanently claimed work. Reuse T-014/T-015 tests, adding only
  missing cross-layer coverage.
- Rehearse restart and backup/restore into a disposable database, including
  the separately managed credential encryption key. Prove documents are
  still searchable after restoration and recovery instructions contain no
  secrets. Never restore over the user's existing database.
- Observe five working days with at least 20 real questions from the
  intended reader, plus five explicit unanswerable controls. Review every
  answer/citation/refusal against the source. Record each miss as a defect
  and an eval candidate with reviewed ground truth.
- Record warm end-to-end answer latency, cold-start latency, sync duration,
  corpus size, device and models. Proposed pilot budget: p95 warm answer
  latency at most 10 seconds across the observed real questions. State the
  small sample size; do not advertise it as a production SLA.
- Provide named owner/support contact, restart/re-sync instructions and a
  pause procedure for a wrong answer, leaked data or stale/deleted citation.

No hosted deployment, multiple reader groups or per-file access control.
Pilot scheduling and human observation are required external inputs; their
absence leaves this ticket blocked. Product defects get separate tickets.

## Success metrics

- All lifecycle and recovery cases pass with zero lost fixture files,
  cross-tenant results, duplicate chunks or deleted/stale content after a
  successful sync. Every failed item has an actionable reason.
- At least 18/20 real questions yield a correct cited answer or an appropriate
  refusal verified against the source; report answerable-question success
  separately so refusing everything cannot pass. At least 90% of answerable
  questions receive a correct cited answer. All five negative controls refuse.
- Zero confident incorrect answers, fabricated citations or privacy leaks;
  any one blocks pilot approval regardless of aggregate scores.
- Five days of evidence, latency budget met, no unresolved release-blocking
  defects, and named product-owner sign-off on the candidate/configuration.

## Test cases

- `pilot_drive_edit_replaces_old_answer_after_sync`
- `pilot_drive_deletion_removes_search_list_and_fetch_results`
- `pilot_unchanged_sync_is_idempotent`
- `pilot_interrupted_sync_recovers_without_lost_files`
- `pilot_bad_file_and_provider_timeout_remain_visible_and_recoverable`
- `pilot_backup_restore_preserves_search_and_connection_recovery`
- `pilot_five_day_answer_citation_refusal_and_latency_review`

## Design notes

These are proposed pilot acceptance targets, not current measurements.
Manual sync is acceptable if documented; freshness is promised after a
successful sync, not in real time. T-031 supplies answer evaluation and
T-033 supplies per-case regression evidence. T-030 transitively brings
the QA report, D0 and client-boundary gate.

## Work log

- 2026-09-17 — Separated ongoing pilot acceptance from the existing demo
  gate; retained incremental sync/deletion implementation in its own tickets.

## Outcome
