---
id: T-029
title: Mirror the backlog into Basira with go2 backlog sync
status: done
phase: 0-process
priority: P1
blocked_by: []
github_issue:
owner: claude-fable-5.1
branch: process/basira-sync
pr: https://github.com/mostafaelkabir/TheGo2Assistant/pull/25
created: 2026-09-16
updated: 2026-09-17
closed: 2026-09-16
---

## Problem

The owner tracks and monitors every project in Basira, their local app
(FastAPI on `127.0.0.1:8001`, Work module of per-company tickets), and on
2026-09-16 asked that work on this repository be picked up and watched
there rather than in GitHub or `backlog/BACKLOG.md`. Today nothing connects
the two: `backlog/` holds 19 tickets, Basira holds none for this project,
and a status change in one is invisible in the other. Copying by hand is
exactly the drift `backlog/` was built to prevent -- a merged PR whose
ticket still says in-progress, now with a second place to be stale.

## Definition

Delivers `go2 backlog sync`: push every ticket in `backlog/tickets/` to
Basira, idempotently, keyed on `ticket_ref = T-NNN` under the
`Go2Assistant` company and project goal. Creates what is missing, updates
title, status, priority, type, tags, description, notes and the PR proof on
what exists. Status maps ready→todo, in-progress→in_progress,
in-review→review, done→done, dropped→done+tag; priority P0..P3 →
urgent..low; a ticket with an open blocker carries the `blocked` tag.
`--dry-run` prints the plan without writing. The command reports Basira
tickets in that company that carry no `T-NNN` ref, so a ticket the owner
adds in Basira becomes a repository ticket instead of being lost.

Does not deliver: pulling status changes from Basira back into the ticket
files (the repository stays the record CI enforces; a status moved in Basira
is a prompt for the agent, not a write), time logging, or comments in
either direction. The company and goal are created once by hand and their
ids are configuration, not discovered by name at every run.

## Success metrics

- After one run against a fresh company, Basira holds exactly one ticket
  per file in `backlog/tickets/` with matching `ticket_ref`, status and
  priority; a second run makes zero writes (idempotent, measured by the
  command's own create/update/unchanged counts).
- Changing a ticket's status in the file and syncing changes exactly that
  Basira ticket's status and nothing else.
- With Basira down, the command fails with a message naming the URL and
  exit 1; it never leaves a half-written ticket (each ticket is one request).
- `go2 backlog check` and the fast tests are unaffected: no network in the
  test suite (the client is exercised through a fake transport).

## Test cases

- `test_a_new_ticket_is_created_with_its_ref_and_goal`
- `test_an_existing_ticket_is_updated_not_duplicated`
- `test_an_unchanged_ticket_makes_no_request`
- `test_status_and_priority_map_to_basira_vocabulary`
- `test_an_open_blocker_adds_the_blocked_tag`
- `test_a_dry_run_writes_nothing`
- `test_basira_tickets_without_a_ref_are_reported`
- `test_an_unreachable_basira_names_the_url`
- `test_an_update_names_the_field_that_differs`
- `test_duplicate_refs_in_basira_are_reported`
- `test_an_unconfigured_mirror_is_off_not_broken`
- `test_a_half_configured_mirror_is_an_error`
- `test_a_remote_basira_url_is_refused`
- `test_a_changed_pull_request_replaces_the_generated_proof`

## Design notes

Basira has no auth on loopback and its API is the app's own; the base URL
and the two ids live in configuration (`GO2_BASIRA_URL`,
`GO2_BASIRA_COMPANY_ID`, `GO2_BASIRA_GOAL_ID`) so the mirror can be pointed
elsewhere or switched off by leaving the ids empty, in which case the
command says so and exits 0 so the edit chain it ends still passes. Nothing about documents
leaves the machine: only ticket text goes to a loopback service, so the
egress guard does not apply. The `ticket` skill and `CLAUDE.md` gain the
sync step after every ticket edit, next to `go2 backlog index`.

## Work log

- 2026-09-16 — Opened and claimed on `process/basira-sync` after the owner
  asked for Basira as the tracking platform. Company and goal created in
  Basira by hand.
- 2026-09-16 — Review: no blockers. Unconfigured now exits 0; updates name
  the differing field; duplicate refs reported; id pattern shared with backlog.
- 2026-09-16 — PR opened: https://github.com/mostafaelkabir/TheGo2Assistant/pull/25
- 2026-09-16 — Codex review: remote GO2_BASIRA_URL now refused (loopback check
  shared with the auth gate); half-configured ids are an error; a changed PR
  replaces the generated proof.
- 2026-09-16 — PR #25 merged.
- 2026-09-17 — Closed. Found still in-review the morning after the merge: the
  close step was missed, which is the drift T-000 warned about.

## Outcome

Shipped in PR #25: `go2 backlog sync [--dry-run]`, `go2/basira.py`, the
three `GO2_BASIRA_*` settings, and the sync step in `CLAUDE.md` and the
`ticket` skill.

Success metrics as measured on 2026-09-17 against the live app:

- Basira holds exactly one ticket per file: 20 files, 20 tickets, every
  `ticket_ref` matching, statuses and priorities mapped as specified. A
  dry run on the morning after reports `would create 0, would update 0,
  unchanged 20`, so the mirror is idempotent.
- Changing one file changes one Basira ticket: the update path names the
  field that differs, covered by `test_an_update_names_the_field_that_differs`.
- Basira down: covered by `test_an_unreachable_basira_names_the_url`;
  each ticket is one request so nothing is half-written.
- No network in the suite: the client runs against a fake transport.

Left out, by design: pulling status back from Basira, comments, and time
logging. One process gap surfaced immediately: this ticket itself sat in
`in-review` for a night after its PR merged, because closing is a manual
step on `main` and nothing reminds anyone. Worth a check that flags an
`in-review` ticket whose PR is merged.
