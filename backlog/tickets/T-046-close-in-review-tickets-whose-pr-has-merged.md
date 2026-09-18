---
id: T-046
title: Close in-review tickets whose PR has merged
status: in-progress
phase: 0-process
priority: P3
blocked_by: []
github_issue:
owner: Claude (Opus 4.8)
branch: process/backlog-pr-close
pr:
created: 2026-09-18
updated: 2026-09-18
closed:
---

## Problem

T-029 sat `in-review` for a night after its PR merged, because closing is
a manual step on `main` and nothing noticed. The roadmap records this as
the one gap seen in the process so far. With several agents picking
tickets in parallel, a merged PR whose ticket still says `in-review` is a
ticket a second agent will not pick up and a Basira board that shows work
as open when it is done. `go2 backlog check` validates the files against
each other and not against GitHub, so it cannot see this.

## Definition

- `go2 backlog check --prs`: for every `in-review` ticket with a `pr:`
  URL, ask `gh pr view --json state,mergedAt` and report tickets whose PR
  is merged, with the merge date, as a warning by default and a failure
  under `--strict`.
- `go2 backlog close T-NNN`: sets `status: done`, `closed:` to the merge
  date from GitHub, adds the Work log line, and opens the file's Outcome
  section for editing by printing the path; it refuses to close a ticket
  whose Outcome is empty, so the human step that matters stays human.
- Both commands run offline-safe: without `gh` or without network they
  say so and skip, never fail the ordinary check.

Does not deliver: automatic closing in CI, or writing an Outcome.

## Success metrics

- A fixture ticket `in-review` with a merged PR is reported by `--prs` and
  fails under `--strict`; one with an open PR is not reported.
- `go2 backlog close` on a ticket with a written Outcome produces a file
  that passes `go2 backlog check`; on one with an empty Outcome it refuses
  and names the section.
- The plain `go2 backlog check` and the fast tests do not call `gh`, so
  CI without GitHub credentials is unchanged.

## Test cases

- `test_merged_pr_on_an_in_review_ticket_is_reported`
- `test_open_pr_is_not_reported`
- `test_strict_mode_fails_on_a_merged_pr`
- `test_close_refuses_an_empty_outcome`
- `test_close_writes_done_closed_and_a_work_log_line`
- `test_check_without_gh_skips_with_a_message`

## Design notes

`gh` is already the way PRs are opened here, so the dependency is not new.
Mock the `gh` call in tests; do not call GitHub from the suite.

## Work log

- 2026-09-18 — Opened from the roadmap's Phase 0 gap, so a parallel agent
  can take it.
- 2026-09-18 — Claimed by Claude (Opus 4.8) on branch
  process/backlog-pr-close.

## Outcome
