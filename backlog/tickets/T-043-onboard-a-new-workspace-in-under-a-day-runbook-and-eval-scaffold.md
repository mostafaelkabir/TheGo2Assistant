---
id: T-043
title: 'Onboard a new workspace in under a day: runbook and eval scaffold'
status: backlog
phase: 2-gate
priority: P2
blocked_by: [T-017, T-033]
github_issue:
owner:
branch:
pr:
created: 2026-09-18
updated: 2026-09-18
closed:
---

## Problem

Rung 2 of the strategy is two or three more offices on the same product,
and it ends when the third one onboards in under a day, measured. Today
there is no record of what onboarding costs. The `dawan` workspace was
created, ingested and given a 20-case eval set by hand over several
sessions, and the only written trace of the steps is scattered across the
roadmap and the LibreChat README. Eval sets are per workspace (the `local`
suite scored 5/17 on `dawan`), so every client costs a suite written by
reading their files, and nothing helps a person write one faster than the
first time.

## Definition

- `docs/onboarding.md`: the runbook from "a client hands over a folder or
  a Drive share" to "a reader asks a question in the chat UI", every step
  a command, including creating the workspace, scanning for sensitive
  values, ingesting, serving with a token, and writing the eval set.
- `go2 evaluate --scaffold WORKSPACE`: writes a YAML skeleton with the
  `tenant` guard, one commented placeholder case per document (title
  filled in, question and expected text left empty), and the refusal
  block copied from the template. It writes no questions and no expected
  text: those are read out of the documents by a person, because a case
  whose answer was guessed measures the guess.
- The onboarding time recorded per workspace in the baselines file from
  T-033, so the number is a record and not a memory.

Does not deliver: LLM-generated eval cases, a Drive picker (T-013), or any
change to ingestion.

## Success metrics

- A second person, not the developer, onboards a fresh workspace of about
  50 files from the runbook only, and the wall-clock time from folder to
  first cited answer is under four hours, recorded.
- A 20-case eval set for that workspace is written and passing in under a
  further four hours, recorded.
- The scaffold for `dawan` lists all 63 documents and validates against
  the eval loader with zero cases enabled.

## Test cases

- `test_scaffold_lists_every_document_in_the_workspace`
- `test_scaffold_carries_the_tenant_guard`
- `test_scaffold_writes_no_question_or_expected_text`
- `test_scaffold_output_loads_as_an_empty_suite`
- `onboard_a_fresh_workspace_from_the_runbook` — manual acceptance, timed.

## Design notes

Blocked by T-017 because the runbook's first step is creating a real
workspace, and by T-033 because the time is recorded where the baselines
live. The scaffold is deliberately dumb; the strategy's position is that
eval quality comes from reading, and a tool that drafts questions would
be used instead of reading.

## Work log

- 2026-09-18 — Opened from the strategy: rung 2 is measured by onboarding
  cost, and nothing measures it.

## Outcome
