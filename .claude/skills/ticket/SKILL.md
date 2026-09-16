---
name: ticket
description: Work the file-based backlog in backlog/ — pick the next ready ticket, claim it, write a new one, or close one after its PR merges. Use when asked to pick up work, start a ticket, open a ticket, or close a ticket, and at the start of any change that has no ticket yet.
---

# Ticket

The backlog is a directory of Markdown files; `backlog/README.md` is the
contract and `go2 backlog check` enforces it. This skill is the sequence of
edits for each transition, so it is done the same way every time.

Arguments: `pick`, `pick T-016`, `new "title" --phase 1-drive`, `close T-016`.
With no argument, `pick`.

## pick

1. `go2 backlog sync --dry-run` first: it reports Basira tickets that have
   no repository id. Each is a request the owner typed into Basira; write a
   ticket for it (`new`, below) before choosing. Then `go2 backlog` — ready
   tickets, highest priority first. If an id was given, use that one; it
   must be `ready` (or `in-progress` with your own name as owner, if
   resuming). Basira's priority and status on the mirrored ticket are the
   owner's latest word; if they differ from the file, update the file.
2. Read the ticket file in full. If `## Test cases` is empty or the
   `## Definition` does not say what is out of scope, fix the ticket before
   claiming it — and say so.
3. Branch: `git switch -c <type>/<short-name>` from a fresh `main`.
4. Edit the ticket: `status: in-progress`, `owner: <your name and model>`,
   `branch: <the branch>`, `updated: <today>`, a dated Work log line.
5. `go2 backlog index && go2 backlog check && go2 backlog sync`.
6. Commit the ticket and the index alone, before any code:
   `git commit -m "T-016: claim"`. Push the branch. The claim is now visible
   to anyone who fetches.
7. Build to the ticket. The named test cases are the tests you write.

## new

1. `go2 backlog new "<title>" --phase <phase> [--priority P2]` prints the
   path of the scaffold.
2. Fill in Problem, Definition, Success metrics and Test cases. The
   placeholders are comments and count as empty; the check refuses an empty
   section. Set `blocked_by` if another ticket has to land first; a ticket
   with an open blocker stays `backlog`, otherwise set it `ready`.
3. `go2 backlog index && go2 backlog check && go2 backlog sync`.
4. Commit: `git commit -m "T-027: open"`. On its own branch if that is all
   the change is, or alongside the work it describes.

## close

Run on `main` after the PR merged.

1. `git switch main && git pull`.
2. Edit the ticket: `status: done`, `closed: <merge date>`, `updated`, a
   Work log line, and write `## Outcome`: what shipped, each success metric
   as actually measured, and anything left out with the ticket that picks it
   up. Leave `owner`, `branch` and `pr` as the record of who did it.
3. `go2 backlog index && go2 backlog check && go2 backlog sync`.
4. `git commit -m "T-016: close" && git push`.
5. If `github_issue` is set: `gh issue close <n> --comment "Closed by <pr url>"`.

## What not to do

- Do not claim a ticket by editing the index; it is generated.
- Do not widen a ticket while working it. New scope is a new ticket.
- Do not mark `done` without an Outcome. The check refuses it, and the
  Outcome is the only place the measured result survives.
