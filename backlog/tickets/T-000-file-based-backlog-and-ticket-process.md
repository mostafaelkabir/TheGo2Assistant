---
id: T-000
title: A file-based backlog, and no code without a ticket
status: in-review
phase: 0-process
priority: P0
blocked_by: []
github_issue:
owner: claude-fable-5.1
branch: process/backlog-and-tickets
pr: https://github.com/mostafaelkabir/TheGo2Assistant/pull/23
created: 2026-09-16
updated: 2026-09-16
closed:
---

## Problem

Work is planned in `docs/roadmap.md` and tracked as GitHub issues, and nothing
connects the two to what actually lands. A PR can merge without the issue it
closes being touched, the roadmap's "done" state is whatever someone last
remembered to edit, and an agent starting a session has no single place that
says what is free to pick up, what is already claimed, and what "done" means
for it. With more than one agent working, two can start the same ticket and
neither can tell.

## Definition

In scope:

- A `backlog/` directory in the repository: one Markdown file per ticket with
  a fixed frontmatter and fixed sections (problem, definition, success
  metrics, test cases, work log, outcome), a generated `BACKLOG.md` index,
  and a `README.md` stating the lifecycle and the rules for agents.
- `go2 backlog` to list, check, index and scaffold tickets, so the format is
  enforced by code rather than by review.
- A fast test that runs the check, so CI refuses a malformed ticket or a
  stale index.
- The working agreement in `CLAUDE.md` and the `/pre-pr` gate updated: no
  code without a ticket; a PR names its ticket; the ticket is updated when
  the PR opens and again when it merges.
- The existing GitHub issues (#10–#19, #21) mirrored as tickets, so the
  local backlog is complete on day one, and the roadmap pointed at it.

Out of scope: syncing tickets to GitHub issues automatically. The issue
number is a field on the ticket; keeping the two in step is a manual step
named in the README.

## Success metrics

- Every open piece of planned work has a ticket file; the index lists them
  and `go2 backlog check` passes on `main`.
- A PR opened after this merges names a ticket id in its body, and that
  ticket is `in-review` with the PR linked before the PR is opened.
- An agent given only "pick the next ticket" can do so from `go2 backlog`
  without reading the roadmap or the issue tracker.
- A malformed ticket, or a status a second agent could trip over (an
  `in-progress` ticket with no owner or branch), fails the fast tests.

## Test cases

- `test_a_valid_ticket_parses`
- `test_a_missing_section_is_rejected`
- `test_in_progress_needs_an_owner_and_a_branch`
- `test_done_needs_a_pr_and_an_outcome`
- `test_a_ready_ticket_cannot_have_an_open_blocker`
- `test_two_in_progress_tickets_cannot_share_a_branch`
- `test_a_duplicate_id_is_rejected`
- `test_the_index_is_deterministic_and_lists_open_before_closed`
- `test_a_stale_index_fails_the_check`
- `test_the_repository_backlog_is_consistent` -- the real check, against
  the committed files

## Design notes

Files, not a service: the backlog has to be readable and editable by an
agent with only a checkout, and reviewable in the same PR as the code it
describes. Git is the audit log. The generated index exists so the overview
is one file, and it is checked rather than trusted so it cannot drift.

The id is local (`T-NNN`) rather than the GitHub issue number, because
issues and PRs share one number space on GitHub and a local id must be
assignable offline. Seeded tickets keep the same number as their issue for
memorability; that is a convenience, not a rule.

## Work log

- 2026-09-16 — Ticket opened. Format, module, CLI, tests, seeded tickets and
  process docs written on `process/backlog-and-tickets`.
- 2026-09-16 — Review found the scaffold wrote titles unquoted; fixed. PR #23
  opened; ticket to in-review.

## Outcome
