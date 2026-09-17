---
id: T-031
title: "Answer-level eval: judge the answer, not only the retrieval"
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

`go2 evaluate` measures whether the right passage is retrieved (rank, MRR,
evidence margin). The product promise is one step further: a correct
answer with a citation, or an honest refusal. That step is the model's,
and `docs/roadmap.md` lists "model tool-calling quality" as a risk with
this exact failure already observed: a small local model skipped the tools
and answered from its own weights. Nothing measures it. A model change,
a prompt change in the MCP instructions, or a provider outage can turn
perfect retrieval into wrong answers and every number stays green.

## Definition

Delivers a second eval mode that drives the real tool loop: for each case,
a model with the four MCP tools answers the question, and a judge scores
the transcript on three binary facts: did it call `search_documents`
before answering; does the answer cite a passage that was actually
returned; does the answer agree with `expect_text` (or refuse when
`expect_no_answer`). Reports answered-correctly, refused-correctly,
answered-without-citation and answered-from-weights as counts, per
workspace, alongside the retrieval numbers.

Does not deliver: a new eval file format (reuses the existing cases),
a judge for free-text quality beyond the three facts, or running this in
CI (it calls a generation provider, so it is a `go2 evaluate --answers`
run, recorded in the ticket that changed something).

## Success metrics

- Baseline recorded for `local` and `dawan` with the configured generation
  model: answered-from-weights must be 0 and answered-without-citation
  must be 0, or the ticket that fixes the prompt is opened before this
  one closes.
- Swapping in a deliberately weak model in a test makes
  answered-from-weights non-zero: the harness can see the failure it
  exists for.
- The run goes through `go2.security.guard.screen` like every other
  generation call; asserted by test.

## Test cases

- `test_an_answer_without_a_tool_call_is_counted_as_from_weights`
- `test_a_citation_not_in_the_returned_passages_is_counted_as_uncited`
- `test_a_refusal_on_an_expect_no_answer_case_passes`
- `test_a_confident_answer_on_an_expect_no_answer_case_fails`
- `test_the_judge_never_sees_document_text_that_did_not_pass_the_guard`

## Design notes

Invariant 1 makes this necessary: because the model drives the loop, the
loop is part of the product and needs its own gauge. Keep the judge
mechanical (three facts) rather than an LLM grading prose, so the number
means the same thing next month. Cost is bounded: 37 cases today, cents
per run on the generation side.

## Work log

- 2026-09-17 — Opened in a product review: the only accuracy figure we can
  quote stops one step short of what the user sees.

## Outcome
