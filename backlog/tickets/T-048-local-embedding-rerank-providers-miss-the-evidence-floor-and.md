---
id: T-048
title: Local embedding/rerank providers miss the evidence floor and peg the CPU inside the stack container
status: ready
phase: 2-gate
priority: P2
blocked_by: []
github_issue:
owner:
branch:
pr:
created: 2026-09-20
updated: 2026-09-20
closed:
---

## Problem

T-047's stand-up (2026-09-18, owner's M2, 16 GB, `deploy/stack/`) ran the
sample eval with `GO2_EMBEDDING_PROVIDER=local` / `GO2_RERANK_PROVIDER=local`
inside the Docker container: it pegged a CPU core, ran hot, and one sample
question's top passage fell a hundredth under the 0.30 evidence floor. The
same question passes at rank 1 with a phrasing change and with the Jina
providers, which dropped search to ~2 s and left the laptop idle. The
ticket shipped by switching the *test* stack to Jina rather than fixing the
local path, which leaves invariant 6 ("retrieval stays local") unverified
under load inside a container — the default is still `local`, but nobody
has shown it clears the floor there.

Separately, the host cannot reach `api.jina.ai` at all over its default
route (IPv6 black-holes) while the *container* reaches it fine over IPv4 —
the same asymmetry that makes the full test suite hang on this host unless
it is pointed at local providers. That asymmetry is itself worth
understanding before anyone relies on it — a stack that silently depends
on the container having better routing than the host is a fragile default
to inherit.

## Definition

Delivers:
- A reproduction of the local-provider run inside `deploy/stack/` (same
  container resource limits as shipped), with `go2 trace` output showing
  where the time and the missed passage went for the failing sample
  question.
- Either a fix (batching, thread pinning, model choice, or the question/
  chunking change the eval itself already suggests) that clears the 0.30
  floor on all seven sample questions with `local` providers inside the
  container within a stated wall-clock budget per query, or, if no fix
  closes the gap on the container's current CPU/memory limits, a written
  finding saying so with the numbers, so the default is a documented
  trade-off instead of a silent one.
- A recorded CPU/memory profile for the local providers inside the
  container, compared against the Jina run's ~2 s figure from T-047.
- A one-paragraph note on the IPv4/IPv6 asymmetry to `api.jina.ai`
  (container vs. host) — not a fix for host routing, just the
  documented cause, so `deploy/stack/README.md`'s egress note stays
  accurate.

Does not deliver: a change to the default provider (invariant 6 keeps
`local` as the on-prem default regardless of outcome), work on the host's
IPv6 route, or a general performance-tuning pass on the embedding
pipeline beyond this container's resource envelope.

## Success metrics

- `go2 evaluate` run with `local` providers inside `deploy/stack/`:
  7/7 sample questions pass, with a stated margin against the 0.30 floor
  for the previously-failing question.
- Per-query wall clock and CPU utilization recorded for the local run
  inside the container, alongside the existing Jina figures from T-047's
  Outcome, so the two are comparable.
- `deploy/stack/README.md`'s egress note states the IPv4/IPv6 asymmetry
  in one sentence, or links to where it is explained.

## Test cases

- `test_local_providers_clear_the_evidence_floor_in_container` — runs the
  sample eval inside the stack with local providers, asserts every
  question's top passage score is >= 0.30 and the correct document is
  cited.
- `test_local_provider_resource_profile_is_recorded` — the ticket's
  Outcome (or a checked-in profile artifact) names CPU and wall-clock
  numbers for the local run, not just "ran hot".

## Design notes

Keep invariant 7 (bounded batch size) in mind — this may be the same
CPU-contention shape, not a new problem. Check `fastembed` batch size and
thread count actually in effect inside the container before assuming the
floor miss is a data/ranking issue rather than a resource one.

## Work log

- 2026-09-20 — Opened from T-047's stand-up finding: local providers
  missed the evidence floor and pegged the CPU inside the container,
  so the shipped stack's test run used Jina instead. `local` remains the
  on-prem default; this ticket verifies it actually clears the bar under
  container resource limits rather than leaving that unverified.

## Outcome
