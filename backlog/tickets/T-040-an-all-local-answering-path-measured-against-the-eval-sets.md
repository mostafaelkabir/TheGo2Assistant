---
id: T-040
title: An all-local answering path, measured against the eval sets
status: backlog
phase: 5-on-prem
priority: P2
blocked_by: [T-018, T-031]
github_issue:
owner:
branch:
pr:
created: 2026-09-18
updated: 2026-09-18
closed:
---

## Problem

Retrieval is local by invariant, but two calls still leave the machine:
generation, which happens in the chat client and goes to Alibaba Model
Studio in Singapore (`model_general`, `model_hard`), and OCR, which T-018
routes to `qwen-vl-ocr`. A bank or a ministry permits neither. The roadmap
already records the risk that a small local model skipped the tools and
answered from its own weights, observed once with no number attached.
Nothing measures what an all-local configuration costs in accuracy or
latency, so the on-prem tier cannot be priced, specified or promised.

## Definition

A documented configuration in which nothing leaves the machine, and the
numbers that say what it costs:

- A local OpenAI-compatible model server (the choice recorded in
  `config.py` as model ids and a base URL, never inline) serving the chat
  client, and a local OCR provider behind the interface T-018 lands.
- `go2 trace` shows zero egress-marked steps across a full run of
  `eval/dawan.yaml` under this configuration.
- The answer-level eval (T-031) and the retrieval eval run under it, and
  the results are published in `docs/on-prem.md` next to the cloud
  numbers on the same suite, on named hardware.
- A minimum hardware specification derived from those runs.

Does not deliver: fine-tuning, a bundled model, the offline installer
(T-042), or a change to the default configuration. The cloud path stays
the default for the wedge.

## Success metrics

- Zero egress steps in every trace of the `dawan` suite under the local
  configuration, asserted by test.
- The local model makes at least one tool call before answering on every
  answerable case; a case answered with no tool call is a failure of this
  ticket regardless of whether the answer was right.
- Every `expect_no_answer` case still refuses.
- Answer-level pass rate on `dawan` under the local model, reported with
  the gap to the cloud model on the same day and commit. No target is set
  before the first measurement; the first run sets the baseline.
- p95 warm answer latency on the reference hardware, recorded.

## Test cases

- `test_all_local_configuration_records_no_egress_step`
- `test_the_local_model_calls_a_tool_before_answering`
- `test_refusals_hold_under_the_local_model`
- `test_local_ocr_provider_returns_page_text_without_egress`
- `test_model_ids_for_the_local_path_live_in_config`
- Both eval suites and the T-031 answer-level suite, under both
  configurations, on the same commit.

## Design notes

Invariant 4 (providers behind interfaces) and 6 (retrieval stays local)
make this a configuration exercise if T-018 lands its OCR behind a
provider. If T-018 lands it as a direct call, this ticket grows a
refactor and should say so in its Work log. The honest fallback if the
numbers are bad is a smaller on-prem product, retrieval and citations
with a lighter generation step, not a worse copy of the cloud product;
the strategy file says this and the Outcome should confirm or deny it.

## Work log

- 2026-09-18 — Opened from the strategy review as the first ticket of the
  on-prem tier: measure before promising.

## Outcome
