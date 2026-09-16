---
id: T-026
title: Hosted deployment behind authentication
status: backlog
phase: 4-second-connector
priority: P3
blocked_by: [T-016, T-019]
github_issue:
owner:
branch:
pr:
created: 2026-09-16
updated: 2026-09-16
closed:
---

## Problem

Everything runs on one laptop. A client cannot use it without that laptop
being on, and a demo on a shared machine cannot happen before T-016 exists.

## Definition

`go2 serve --http` and the worker running on a machine that is not a
laptop, behind T-016's token, with T-019's redaction on, and the database
and model cache provisioned by a documented script in `deploy/`. Retrieval
still runs locally on that host (invariant 6); only generation calls out.

## Success metrics

- A fresh host reaches "answers a question with a citation" by following
  `deploy/README.md` alone.
- Search latency on the host is recorded next to the laptop's 0.4 s and
  3.4 s figures, since a cheap cloud CPU is slower than an M2.

## Test cases

- A smoke script in `deploy/` that ingests one file and runs one search,
  exiting non-zero if the citation is missing.

## Design notes

## Work log

- 2026-09-16 — Opened from the roadmap's Phase 4.

## Outcome
