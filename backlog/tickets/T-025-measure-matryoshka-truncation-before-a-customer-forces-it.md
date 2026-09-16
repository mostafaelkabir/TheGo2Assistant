---
id: T-025
title: Measure Matryoshka truncation before a customer forces it
status: ready
phase: 3-accuracy
priority: P3
blocked_by: []
github_issue:
owner:
branch:
pr:
created: 2026-09-16
updated: 2026-09-16
closed:
---

## Problem

The HNSW index wants its vectors resident: projected 64 GB of working set at
a million documents, which forces a bigger machine somewhere around a
hundred thousand. The embeddings are Matryoshka-truncatable to 512 or 256
dimensions, which would cut that by half or three quarters, but the accuracy
cost has not been measured here. It should be measured before a customer
with 500,000 documents makes the decision under pressure.

## Definition

Run both eval suites at full, 512 and 256 dimensions on a throwaway copy of
the index, and record rank, MRR and the evidence margin for each. Write the
result into `docs/roadmap.md` under Risks. No production change.

## Success metrics

- A table in the roadmap with MRR and margin at three dimensions for both
  workspaces, and a stated recommendation.

## Test cases

- None: this is a measurement, not a behaviour change. The output is the
  table and the recommendation.

## Design notes

Vectors carry provenance, so a truncated index must record a distinct model
id or search will mix incomparable vectors silently.

## Work log

- 2026-09-16 — Opened from the roadmap's Risks section.

## Outcome
