---
id: T-044
title: 'Near-duplicate revisions: collapse in results and show the date'
status: ready
phase: 3-accuracy
priority: P2
blocked_by: []
github_issue:
owner:
branch:
pr:
created: 2026-09-18
updated: 2026-09-18
closed:
---

## Problem

Measured on 2026-09-18 in `dawan`. "How are dates ejected into their
categories on the sorting line?" returns:

```
1. DATES SORTING MACHINE 12-13-2023.pdf p.7   [0.648]
2. DATES SORTING MACHINE01-04-2024.pdf p.7    [0.641]
3. DATES SORTING MACHINE01-04-2024.pdf p.6    [0.483]
4. DATES SORTING MACHINE 12-13-2023.pdf p.6   [0.454]
```

Two revisions of one proposal, a month apart, with identical text on the
cited pages, occupy four of the five slots the model sees. The passages
the tool returns carry `title`, `location`, `citation`, `source`, `score`
and `web_url`, and not `modified_at`, although the hit already loads it.
So the model cannot tell which revision is current, and a reader gets
either two citations for one fact or, worse, the older one. A bank's
corpus is this problem at scale: circulars are superseded by circulars,
and the current rule is the whole value of the answer.

## Definition

- Return `modified_at` on every passage, and the guidance line tells the
  model to prefer the most recent revision when passages are near-identical
  and to say which revision it cited.
- Collapse near-duplicate passages in the returned set: when two passages
  from different documents share the same location and their text is
  identical after whitespace normalisation, keep the most recently
  modified one and list the others as `also_in` on that passage, so the
  slot goes to a different fact and the reader still learns the duplicate
  exists.
- The collapse happens after reranking and before the evidence gate, and
  never removes a passage that is the only one above the floor.

Does not deliver: document-level deduplication at ingest, version
tracking across syncs, or any change to the vector or full-text legs.

## Success metrics

- The query above returns the January 2024 revision first with the
  December 2023 one listed under `also_in`, and the third slot holds a
  passage from a different page or document.
- `dawan` stays at or above 19/20, MRR 0.97; `local` at or above 16/17,
  MRR 0.94. Every `expect_no_answer` case still refuses.
- Every passage in every tool response carries `modified_at` (null when
  the source has none), asserted by test.
- Median search latency on the `dawan` suite changes by less than 5%.

## Test cases

- `test_passages_carry_modified_at`
- `test_identical_passages_from_two_revisions_collapse_to_the_newest`
- `test_a_collapsed_passage_lists_the_other_revisions`
- `test_collapse_never_removes_the_only_passage_above_the_floor`
- `test_different_text_at_the_same_location_is_not_collapsed`
- Both eval suites, compared against the baselines.

## Design notes

Touches `go2/tools/search.py` and the guidance text the model reads. The
collapse compares text, not embeddings, because the case that matters is
literally identical pages, and a similarity threshold would start merging
the two CQ-XP1010 quotations, which hybrid search exists to keep apart.
The `also_in` list is what makes this safe for a bank: the superseded
circular is still visible, it just does not win the slot.

## Work log

- 2026-09-18 — Opened from the use-cases review, where the two revisions
  of the sorting-machine proposal filled four of five slots.

## Outcome
