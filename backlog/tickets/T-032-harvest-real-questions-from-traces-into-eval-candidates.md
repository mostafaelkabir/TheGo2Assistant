---
id: T-032
title: Harvest real questions from traces into eval candidates
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

T-023 asks for several hundred eval cases "drawn from real use", and
invariant 8 says every bad answer becomes a case. In practice a bad answer
is noticed in a chat window, the moment passes, and the case is never
written: the two suites are still at 17 and 20 after two weeks of use.
The traces already record every question, its verdict and its top
citation; the gap is the step from trace to case.

## Definition

`go2 trace --export-cases [--since DATE] [--verdict refused|answered]`
writes a YAML fragment of candidate cases from recent traces: the
question, the top citation as `expect_documents`, the verdict, and a
`review: true` marker so a candidate can never be mistaken for a reviewed
case. `go2 evaluate` refuses a file containing an unreviewed candidate.
A reviewed case is one where a person read the document and either kept
the expected citation, corrected it, or marked `expect_no_answer`.

Does not deliver: automatic acceptance of a case (the harness would then
measure whatever the system already does), or any new trace field.

## Success metrics

- The time from "that answer was wrong" to a committed eval case is one
  command plus one edit; measured by doing it for the next ten bad answers
  and recording the count in the Outcome.
- The `dawan` suite grows by at least 30 reviewed cases from real traces
  within the ticket, with the baseline re-recorded.
- `go2 evaluate` exits non-zero on a file with `review: true` anywhere.

## Test cases

- `test_export_writes_one_candidate_per_trace_with_the_review_marker`
- `test_since_filters_by_trace_time`
- `test_evaluate_refuses_an_unreviewed_candidate`
- `test_a_refused_trace_exports_as_an_expect_no_answer_candidate`

## Design notes

This is the mechanism T-023 needs to be achievable rather than heroic.
T-023 stays the goal ticket (the number of cases); this one is the tool.
Traces record query summaries only; check that the full question text is
available before promising it, and if it is not, storing it is a design
decision to record here first.

## Work log

- 2026-09-17 — Opened in a product review as the missing step between
  invariant 8 and the size of the eval sets.

## Outcome
