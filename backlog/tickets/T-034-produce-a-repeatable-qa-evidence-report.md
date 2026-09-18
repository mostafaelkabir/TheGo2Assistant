---
id: T-034
title: Produce a repeatable QA evidence report
status: ready
phase: 0-process
priority: P1
blocked_by: []
github_issue:
owner:
branch:
pr:
created: 2026-09-17
updated: 2026-09-17
closed:
---

## Problem

CI already runs toolchain, fast tests and the full suite with PostgreSQL and
real models. However, no release QA report connects those results to the
candidate commit, workspace, retrieval evaluation and manual acceptance.
The local fast run on 2026-09-17 reported 315 passed, 2 skipped and 36
deselected; it cannot establish product readiness. T-030 describes a
rehearsal but has no common evidence format. This is an evidence gap, not a
claim that CI is missing or that the product has failed these checks.

## Definition

Deliver a small QA runner (a repository script is sufficient) and a report
template under `docs/qa/`. Reuse existing commands and CI results. Record:

- Commit, dirty-tree status, UTC time, operator, machine/OS, dependency lock
  hash, workspace, corpus counts and fingerprint, configured model IDs,
  evidence threshold, provider choice and redaction mode. Allowlist config
  fields; never dump environment variables or credentials.
- Commands, exit codes, duration, passed/failed/skipped/deselected counts,
  skip reasons and evidence paths for toolchain, backlog check, full tests,
  retrieval eval and manual acceptance. Use JSON and a readable Markdown
  summary; a CI URL is acceptable evidence only for the same commit.
- Explicit PASS, FAIL, BLOCKED and NOT RUN states per required check. A
  missing database/corpus, skipped required test, absent evidence, different
  commit or dirty release tree cannot result in a passing release report.
- Distinguish engineering checks from demo sign-off (T-030) and pilot
  sign-off (T-037). Manual results require a named reviewer and case-level
  evidence; the runner must never invent them.

Do not add another CI pipeline or an evaluation engine. Until T-033 lands,
attach existing retrieval output and explicit reviewer comparison; do not
claim automatic regression detection. After it lands, consume its baseline.
Customer transcripts stay in access-controlled local storage; commit only
sanitized manifests/results and references. Document the command in
`docs/qa-plan.md` when it exists, otherwise create that document.

## Success metrics

- One invocation produces a report even when a subprocess fails.
- Every required check has a state and evidence reference; missing evidence
  returns a nonzero release-gate exit code with an actionable explanation.
- All negative fixture reports below fail the gate; a complete matching
  fixture passes. A real engineering run is attached without falsely marking
  demo or pilot checks as passed.
- No secrets or customer document text in the generated public summary.

## Test cases

- `test_failed_command_is_recorded_and_fails_qa`
- `test_missing_database_or_corpus_blocks_qa`
- `test_skipped_required_tests_cannot_pass_qa`
- `test_missing_manual_evidence_blocks_release_signoff`
- `test_evidence_for_another_commit_or_dirty_tree_is_rejected`
- `test_qa_report_only_serializes_allowlisted_configuration`
- `test_complete_same_commit_evidence_passes_requested_gate`

## Design notes

Start with `.github/workflows/ci.yml`, `.claude/skills/pre-pr/SKILL.md`,
`go2/evaluation.py` and `tests/test_backlog.py`. Keep the mechanism small;
the report records facts and gate policy, not subjective answer judging.
Claude can implement this independently, but the single-agent default
remains finishing T-010 through T-012 first.

## Work log

- 2026-09-17 — Created during product/QA review; engineering checks exist,
  release evidence and an explicit incomplete state do not.

## Outcome
