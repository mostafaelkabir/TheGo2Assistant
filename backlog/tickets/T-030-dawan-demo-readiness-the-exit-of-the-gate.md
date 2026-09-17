---
id: T-030
title: "Dawan demo readiness: the exit criterion for Phase 2"
status: backlog
phase: 2-gate
priority: P1
blocked_by: [T-012, T-017, T-018, T-019]
github_issue:
owner:
branch:
pr:
created: 2026-09-17
updated: 2026-09-17
closed:
---

## Problem

Phase 2 is called "a gate, not a backlog", but nothing says what passing
it looks like. Four tickets sit under it, and when the last one merges the
question "can we show this to Dawan?" will still be answered by feeling.
Each ticket proves its own mechanism; none proves the product: that a
person from Dawan can ask ten questions about their own files and get
cited answers or honest refusals, on a machine that is not the developer's
laptop, without seeing HaramBlur's documents or a third party's phone
number.

## Definition

A scripted, rehearsed demo and the checklist that gates it. Delivers:

- `docs/demo-dawan.md`: ten questions chosen from Dawan's real files (at
  least two answered from a scanned PDF, two from a spreadsheet figure, two
  in Arabic, two that the corpus cannot answer and must be refused), the
  expected citation for each, and the runbook to stand the demo up from a
  clean checkout.
- The rehearsal run recorded in this ticket's Outcome: each question,
  what came back, pass or fail.
- Every checklist item is a shipped ticket or a measured fact, not a
  belief: T-016 token on, T-019 redaction on, `dawan` isolated from
  `local` (T-017), OCR'd files answerable (T-018), at least one live Drive
  document in the workspace (T-012).

Does not deliver: any new mechanism. If the rehearsal finds one missing,
that is a new ticket that blocks this one.

## Success metrics

- Rehearsal on a non-developer machine: at least 8 of 10 questions
  answered correctly with a verifiable citation, and 0 confident wrong
  answers. Both `expect_no_answer` questions refused.
- Zero passages from any other workspace in any answer.
- Stand-up from clean checkout to first answer under 30 minutes, following
  the runbook only.

## Test cases

- The ten questions are added to `eval/dawan.yaml` so the demo set is
  re-run by `go2 evaluate` forever after; the rehearsal is the first run.
- No new unit tests: this ticket consumes the ones its blockers deliver.

## Design notes

This is the ticket the owner reads to know whether Phase 2 is over. Its
blockers are the four gate tickets plus T-012, because a demo with only
locally uploaded files does not demonstrate the product's promise.
T-027 and T-028 are deliberately not blockers: Dawan is one workspace with
one reader group, so a single token per process is the honest first
deployment. Per-user roles are the second client's problem.

## Work log

- 2026-09-17 — Opened in a product review: Phase 2 had four mechanisms and
  no exit criterion.

## Outcome
