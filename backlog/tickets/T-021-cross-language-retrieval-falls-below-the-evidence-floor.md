---
id: T-021
title: Cross-language retrieval falls below the evidence floor
status: ready
phase: 3-accuracy
priority: P1
blocked_by: []
github_issue: 21
owner:
branch:
pr:
created: 2026-09-03
updated: 2026-09-16
closed:
---

## Problem

Measured, not suspected. Asking the same question in Arabic instead of
English, against the same English document, costs a mean of **0.198** of
score. Three of five test pairs fall under the 0.30 evidence floor, so the
assistant declines questions it can answer.

| EN | AR | drop | AR passes gate |
|---|---|---|---|
| 0.672 | 0.536 | +0.136 | yes |
| 0.419 | 0.185 | +0.234 | **no** |
| 0.479 | 0.212 | +0.267 | **no** |
| 0.282 | 0.309 | −0.028 | yes |
| 0.551 | 0.172 | +0.380 | **no** |

This is not "Arabic scores lower": Arabic against Arabic scores 0.543, higher
than an English pair at 0.342. The penalty is specifically cross-language.
Threshold tuning cannot fix it: a correct Arabic query scores 0.185 while a
correct refusal scores 0.22, so the bands overlap.

## Definition

A retrieval-side fix, tried in order of cost:

1. Embed the query in both languages and fuse: cheap, no re-index.
2. A reranker with stronger cross-lingual alignment.
3. Index a translated title or summary per document: touches ingestion.

Start with (1) and measure. **Do not** lower `min_evidence_score`.

## Success metrics

- The KNOWN FAILING case in `eval/dawan.yaml` passes.
- `local` stays at or above 16/17, MRR 0.94; `dawan` at or above 19/20,
  MRR 0.97.
- Every `expect_no_answer` case still refuses.
- Arabic-to-Arabic does not regress from 0.543.

## Test cases

- `test_an_arabic_query_finds_an_english_document_above_the_floor`
- `test_the_english_equivalent_still_scores_at_least_as_well`
- `test_refusals_still_refuse`
- `test_arabic_to_arabic_does_not_regress`
- Both eval suites, compared against the baselines above.

## Design notes

The Dawan margin is only +0.08 (weakest accepted 0.30, strongest refused
0.22). Spending it here buys false answers instead of false refusals.

## Work log

- 2026-09-03 — Opened as GitHub issue #21 with the measurements above.
- 2026-09-16 — Mirrored into the local backlog.

## Outcome
