---
id: T-023
title: Grow the eval sets to several hundred questions from real use
status: ready
phase: 3-accuracy
priority: P2
blocked_by: []
github_issue:
owner:
branch:
pr:
created: 2026-09-16
updated: 2026-09-17
closed:
---

## Problem

`local` has 17 cases and `dawan` has 20. That is a smoke test: enough to
catch retrieval breaking outright, nowhere near enough to quote an accuracy
figure to a customer, and too small to see a five-point drift. Retrieval
regressions are silent, and the eval is the only thing that catches them.

## Definition

Grow both suites to at least 200 cases each, drawn from real questions asked
through the MCP server (the trace log records them) rather than invented.
Each case is written after reading the document it targets. Include
`expect_no_answer` cases in proportion to real refusals. Record the new
baselines in `docs/roadmap.md` and the `/pre-pr` skill.

## Success metrics

- `eval/questions.yaml` ≥ 200 cases; `eval/dawan.yaml` ≥ 200 cases.
- At least 20% of each suite are `expect_no_answer` cases.
- Baselines recorded, and the pre-PR gate compares against them.

## Test cases

- The eval harness already tests itself; this ticket adds data, not code.
- `test_every_case_names_a_document_the_workspace_holds` -- guards against
  a case written for the wrong corpus.

## Design notes

Eval is a per-client onboarding cost, not a one-time build: the `local`
suite scored 5/17 on `dawan`. Each workspace needs its own.

## Work log

- 2026-09-16 — Opened from the roadmap's Phase 3 "remaining work".
- 2026-09-17 — Product review: T-032 (harvest from traces) is the mechanism
  that makes this achievable; do that first. T-033 records the baselines
  this ticket will move.

## Outcome
