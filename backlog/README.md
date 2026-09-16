# Backlog

One Markdown file per ticket under `tickets/`, a generated index in
[`BACKLOG.md`](BACKLOG.md), and `go2 backlog` to keep the two honest. Git is
the audit log. There is no service to be logged into, so any agent with a
checkout can read the queue, claim work, and record what it did.

The roadmap in [`../docs/roadmap.md`](../docs/roadmap.md) says *why* and *in
what order*. This directory says *what, exactly, and is it done*.

## The rule

**No code without a ticket.** Before the first line of a change is written,
a ticket exists with a problem statement, a definition of what is and is not
in scope, success metrics, and the test cases that define done. A change
that arrives without one gets a ticket written first, then reviewed against
it. The exception is a fix small enough to describe fully in its commit
message, and "small enough" means a reviewer would not ask "why?".

The ticket is updated twice more: when the pull request opens, and when it
merges. A merged PR whose ticket still says `in-progress` is the bug this
directory exists to prevent.

## Lifecycle

```
backlog ──▶ ready ──▶ in-progress ──▶ in-review ──▶ done
                                                 └─▶ dropped
```

| Status | Meaning | Required fields |
|---|---|---|
| `backlog` | Written, but something it depends on is open, or it is not yet next | — |
| `ready` | Every `blocked_by` ticket is closed; anyone may pick it up | — |
| `in-progress` | Someone holds it | `owner`, `branch` |
| `in-review` | A pull request is open | `pr` |
| `done` | The PR merged | `pr`, `closed`, a written `## Outcome` |
| `dropped` | Will not be done | `closed`, a `## Outcome` saying why |

`go2 backlog check` refuses a file that breaks these, and the fast tests run
the check, so CI refuses it too. The rules are the minimum that lets several
agents share a text file: an `in-progress` ticket without an owner is one a
second agent will take; a `done` ticket without an outcome is one nobody
can learn from.

## Working a ticket, as an agent

1. **Find work.** `go2 backlog` lists what is `ready`, highest priority
   first. Read the ticket file, not just the row.
2. **Claim it.** Set `status: in-progress`, `owner:` (your name and model),
   `branch:`, bump `updated:`, add a Work log line. Regenerate the index
   with `go2 backlog index`. Commit that on your branch first, so the claim
   is visible to anyone who fetches.
3. **Build to the ticket.** The test cases it names are the tests you
   write. If the work reveals the ticket is wrong, change the ticket in the
   same PR and say so in the Work log; do not quietly build something else.
4. **Open the PR.** Through `/pre-pr`. Set `status: in-review`, fill `pr:`
   with the URL, regenerate the index, and include that in the PR. The PR
   body names the ticket id.
5. **After merge.** On `main`, set `status: done`, `closed:` to the merge
   date, and write `## Outcome`: what shipped, what the success metrics
   measured, and anything left out. Regenerate the index. Commit directly
   to `main` with a message like `T-016: close`. If the ticket mirrors a
   GitHub issue, close the issue with a link to the PR.

Anything you learn that is out of scope becomes a *new* ticket with
`go2 backlog new "title" --phase ...`, not a paragraph in the current one.

## Basira

The owner watches progress in [Basira](../docs/architecture.md), their local
tracking app, not here. `go2 backlog sync` mirrors every ticket file into it
as a work ticket under the `Go2Assistant` company and goal, keyed on the
ticket id, and is run after every ticket edit alongside `go2 backlog index`.
It is one-way: these files are the record CI enforces. A status moved in
Basira is a prompt to update the file; a Basira ticket with no `T-NNN` ref
is a request the owner typed into the app, and the sync reports it so a
ticket gets written for it here.

## Writing a ticket

Copy [`TEMPLATE.md`](TEMPLATE.md), or run:

```bash
go2 backlog new "Deletions must drop their chunks" --phase 1-drive --priority P2
```

Each section has a job:

- **Problem.** What is wrong today, with evidence. Measured, not suspected.
  If you cannot show it, the ticket is a guess and should say so.
- **Definition.** What this ticket delivers, and what it explicitly does
  not. The second half is what stops scope creep in review.
- **Success metrics.** How we will know it worked, in numbers where a number
  exists, and how to measure them. "Search latency under 0.5 s on the dawan
  suite" is a metric; "search is fast" is not.
- **Test cases.** Named tests. A ticket without them is a wish.
- **Design notes.** Constraints, invariants touched, options considered.
- **Work log.** Dated, one line per meaningful step.
- **Outcome.** Empty until the PR merges. Then: what shipped, the metrics
  as measured, what was left out and why.

Ids are `T-NNN`, assigned by `go2 backlog new` as the next free number. They
are local on purpose: GitHub issues and pull requests share one number
space, and a ticket must be creatable offline. `github_issue:` links the two
when both exist.

Priorities: `P0` gates something (a demo, a release); `P1` is next; `P2`
matters and can wait; `P3` is recorded so it is not forgotten.

Phases match the roadmap: `0-process`, `1-drive`, `2-gate`, `3-accuracy`,
`4-second-connector`.

## Commands

```bash
go2 backlog                      # what is ready to pick up
go2 backlog --all                # every open ticket with holder and blockers
go2 backlog check                # validate every ticket and the index
go2 backlog index                # regenerate BACKLOG.md
go2 backlog sync [--dry-run]     # mirror the tickets into Basira
go2 backlog new "title" --phase 1-drive [--priority P2]
```
