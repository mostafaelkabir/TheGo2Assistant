---
id: T-033
title: Eval baselines in one file, not three documents
status: ready
phase: 3-accuracy
priority: P2
blocked_by: []
github_issue:
owner:
branch:
pr:
created: 2026-09-17
updated: 2026-09-17
closed:
---

## Problem

The retrieval baselines (`local` 16/17 at MRR 0.94, `dawan` 19/20 at MRR
0.97) are typed by hand into `docs/roadmap.md`, the `/pre-pr` skill and
T-021. Three tickets (T-021, T-023, T-032) will each move them. The
pre-PR gate compares a fresh run against a number a person remembered to
update, which is the same silent-drift problem the eval exists to catch,
one level up.

## Definition

`eval/baselines.yaml`: one entry per suite with passed, rank-1, MRR,
margin, the embedding model id, and the date and commit it was recorded
at. `go2 evaluate` compares against it by default and exits non-zero on a
drop, and `go2 evaluate --record` rewrites the entry. The pre-PR skill and
the roadmap point at the file instead of quoting numbers.

Does not deliver: tolerance bands beyond "not lower", or per-case history.

## Success metrics

- A retrieval regression of one case fails `go2 evaluate` without anyone
  editing a document.
- The three hand-typed copies are gone; `grep -rn "MRR 0.9" docs .claude`
  finds nothing.
- Recording a baseline stores the embedding model id, so a baseline from
  one model is never compared against a run on another (vectors carry
  provenance; so should their scores).

## Test cases

- `test_a_drop_in_passed_fails_the_run`
- `test_a_drop_in_mrr_fails_the_run`
- `test_record_rewrites_only_that_suite`
- `test_a_baseline_from_another_model_is_refused_not_compared`
- `test_no_baseline_file_warns_and_passes`

## Design notes

Small, and it should land before T-021 so that fix is measured against a
recorded number rather than a remembered one.

## Work log

- 2026-09-17 — Opened in a product review while checking whether the
  pre-PR gate's numbers were still the live ones.

## Outcome
