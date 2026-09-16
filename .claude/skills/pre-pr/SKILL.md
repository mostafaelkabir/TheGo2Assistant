---
name: pre-pr
description: Gate a branch before a pull request exists. Runs the toolchain and the full test suite, then hands the diff to an independent reviewer agent that re-runs the tests itself and reviews against the architectural invariants. Use before `gh pr create`, or whenever asked to open, raise, or prepare a PR.
---

# Pre-PR gate

CI is the backstop. This is the gate. A failure should never first appear on a
pull request that other people are already looking at.

Work through the steps in order. A blocker at any step sends you back to the
code, not forward to the next step.

## 1. Establish what is under review

```bash
git branch --show-current
git status --short
git diff main...HEAD --stat
```

Stop if the branch is `main` — the work needs a branch first. Stop if the diff
is empty. Uncommitted changes are part of the review; commit them or explain
why they are excluded before continuing.

Then find the ticket. Every change starts from one (`CLAUDE.md`, "no code
without a ticket"):

```bash
grep -l "^branch: $(git branch --show-current)$" backlog/tickets/*.md
```

Stop if nothing matches and the diff is more than a commit message can
explain: write the ticket now with `go2 backlog new`, claim it on this
branch, and continue. Read the ticket's `## Test cases` — those are the tests
the diff must contain, and `## Definition` says what it must not contain.

## 2. The toolchain

Non-negotiable, per `CLAUDE.md`:

```bash
uv run ruff format . && uv run ruff check --fix . && uv run pyrefly check
```

Fix everything it reports. A new `# noqa` or `# type: ignore` is a finding
unless it carries an inline comment arguing why the rule is wrong *here*, and a
new entry in `ignore` in `pyproject.toml` is a blocker — that list is closed at
two.

## 3. The full suite, not the fast one

```bash
uv run pytest
```

The full suite, not `-m "not slow"`. The slow tests are the ones that catch a
dimension mismatch, a bad vector literal or a broken cascade.

`slow` marks two different costs, and they fail differently. `test_embedding.py`
is slow because it loads real weights — roughly 600 MB on a first run, and it
does not skip, it just takes a while. The four modules that additionally need
PostgreSQL on port 5433 are `test_ingest_e2e.py`, `test_tenancy.py`,
`test_retrieval.py` and `test_mcp_server.py`, and those skip themselves when
nothing answers.

**If those four report as skipped, the database is not running** — do not go
looking at the model cache. Start it (`docker compose up -d db`, or the
Homebrew `postgresql@17`) and run again.

Read the count, not the colour. The suite was 331 tests when this was written;
`uv run pytest -q -rs` names anything that skipped. A green run that skipped
the database tests has proved nothing, which is worse than a red one.

## 4. Retrieval changes have to clear the eval

If the diff touches `go2/rag/`, `go2/tools/`, `go2/storage/repository.py` or any
migration, run the suites for every workspace that has one:

```bash
GO2_TENANT=local go2 evaluate
GO2_TENANT=dawan go2 evaluate eval/dawan.yaml
```

Compare against the baselines recorded in `docs/roadmap.md` — `local` 16/17 at
MRR 0.94, `dawan` 19/20 at MRR 0.97. A drop is a blocker.

If a workspace holds no documents on this machine, skip its suite and say so
rather than reporting the number. The `tenant:` key in an eval file refuses to
run against the *wrong* workspace, but nothing catches an *empty* one: it
returns a plausible, terrible score that reads exactly like a regression and is
a missing corpus.

Retrieval regressions are silent: the system keeps returning confident-looking
passages, just the wrong ones. That is why invariant 8 exists — a fix landed
without a case covering it will regress and nothing will say so.

## 5. Independent review

Spawn **one** subagent with the Agent tool — `agent-skills:code-reviewer` if
that type is available, otherwise `general-purpose`.

Give it the branch name and let it read the diff itself. Do not paste your
summary of the change: your summary is part of what is being reviewed, and an
agent handed your framing will mostly confirm it.

Its brief:

> Review the diff between `main` and `<branch>` in this repository.
>
> Read `CLAUDE.md` first — it lists nine architectural invariants that are
> load-bearing. Breaking one is a design decision, not a refactor, and a diff
> that breaks one silently is a blocker.
>
> Run the checks yourself rather than trusting a report of them. Run
> `uv run ruff format --check . && uv run ruff check . && uv run pyrefly check`
> and `uv run pytest`, and quote the real output in your findings. If the slow
> tests skip, say so — that means no database was reachable and the suite did
> not test what it appears to have tested.
>
> Review for, in this order: correctness against what the change claims to do;
> whether anything reaches a third party without passing through
> `go2.security.guard.screen`; tenant scoping on every new query and write;
> whether a new suppression is justified in an inline comment; test coverage of
> the actual behaviour rather than of the implementation.
>
> Report findings as **blockers** and **notes**, separately. Do not fix
> anything. Say plainly if you found nothing — a review that manufactures a
> finding to look thorough costs more than it saves.

## 6. Triage

Fix every blocker, then re-run steps 2 through 4. Notes either get fixed or get
a sentence in the PR body saying why not.

Do not spawn a second reviewer to overturn the first. If you think a finding is
wrong, say why in your own words and let the human decide.

## 7. Open it

Commit, push, and open the PR. The body names the ticket id, what changed,
and what the reviewer flagged along with what you did about it.

Then move the ticket: `status: in-review`, `pr:` set to the PR URL, a Work
log line, `updated:` bumped, `go2 backlog index` and `go2 backlog sync`. Commit
that to the same branch and push again, so the PR carries its own ticket update.

After the merge, the ticket is closed on `main`: `status: done`, `closed:`,
and a written `## Outcome` with the success metrics as measured.

```bash
git push -u origin "$(git branch --show-current)"
gh pr create --fill
```

CI will then re-run the toolchain and the fast tests, and run the full suite
against a real pgvector service. It should find nothing you have not already
seen.
