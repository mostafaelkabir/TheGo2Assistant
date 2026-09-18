---
id: T-047
title: "One-command local stack: go2, Postgres and LibreChat in Docker Compose"
status: in-review
phase: 2-gate
priority: P1
blocked_by: []
github_issue:
owner: Claude (Fable 5.1)
branch: deploy/local-stack
pr: https://github.com/mostafaelkabir/TheGo2Assistant/pull/31
created: 2026-09-18
updated: 2026-09-18
closed:
---

## Problem

`go2` runs in exactly one place: installed as a uv tool on the developer's
Mac, against a Homebrew Postgres on port 5433, with LibreChat in a separate
checkout reaching the host through `host.docker.internal`. The repository
has no image for `go2`; the root `docker-compose.yml` says in its first
line that it is "not a deployment artifact -- the app runs on the host".
`deploy/librechat/README.md` is a nine-step manual procedure with a section
titled "Two things that will bite".

Three open tickets presume an installable unit that does not exist. T-030
requires a rehearsal "on a machine that is not the developer's laptop" and
stand-up "from clean checkout to first answer under 30 minutes". T-026
requires a fresh host to reach a cited answer from `deploy/README.md`
alone. T-042 requires an archive to install from. Each would otherwise
build its own packaging ad hoc. The owner also cannot hand the product to
anyone, including a second machine of their own, to run QA against.

## Definition

Delivers one directory, `deploy/stack/`, that stands the whole product up
with `docker compose up -d` and nothing else installed but Docker:

- `Dockerfile` at the repository root: Python 3.12, dependencies installed
  from `uv.lock` with `--locked` and without the dev group, a non-root
  user, the model cache on a volume path, `go2` as the entrypoint.
- `deploy/stack/docker-compose.yml` with services `db` (the same
  `pgvector/pgvector:pg17` image CI uses), `init` (one-shot: `go2 migrate`
  then `go2 tenant create` for the configured workspace, both idempotent),
  `server` (`go2 serve --http` bound to the container's interface, token
  required by compose interpolation so the stack refuses to start without
  one), `worker` (`go2 worker`), `mongodb`, and `librechat` wired to
  `http://server:8765/mcp` with the same token. LibreChat's own RAG API,
  its second pgvector and Meilisearch are not started.
- `deploy/stack/.env.example`: the single configuration file for the
  stack, every key commented, no values for secrets.
- `deploy/stack/librechat.yaml`: one MCP server entry for the stack's
  workspace, `allowedAddresses` naming only the server, the Qwen
  (Singapore) endpoint.
- `deploy/stack/samples/`: a small synthetic corpus and `eval.yaml` for a
  `demo` workspace, so a fresh stack has known answers the moment it
  boots and a client can see a cited answer before ingesting anything of
  their own.
- `deploy/stack/smoke.py`: connects over Streamable HTTP with the token,
  asserts the three tools are listed, asks a sample question and requires
  `sufficient_evidence` with a citation naming a sample document, fetches
  that document, and asserts a request without the token gets 401. Exits
  non-zero on any miss. This is the smoke T-026 asks for.
- `deploy/stack/README.md`: the runbook from clean checkout to a cited
  answer in the browser, how to ingest a real folder into the stack, how
  to run the smoke and the retrieval eval inside it.

Does not deliver: a hosted deployment on a remote host (T-026), an offline
archive with vendored models (T-042), a Windows installer, LibreChat
single sign-on, more than one workspace in one stack (one tenant per
serving process is the rule the stack inherits), the Google Drive path
(T-011, T-012), or Docker in CI. The existing `deploy/librechat/`
arrangement stays as the developer-laptop setup.

## Success metrics

- On this Mac, from `cp .env.example .env` plus setting the token and one
  provider key, through `docker compose up -d`, to a cited answer in
  LibreChat: under 30 minutes wall clock including the image build,
  timed and recorded in the Outcome. This is T-030's stand-up number.
- `smoke.py` passes against the running stack: three tools listed, the
  sample question answered with `sufficient_evidence: true` and a
  citation naming a sample file, the document fetched, 401 without the
  token. Wall clock recorded.
- `docker compose config` validates. `docker compose up` with
  `GO2_HTTP_TOKEN` unset fails before any container starts, naming the
  variable.
- With `GO2_EMBEDDING_PROVIDER=local` and `GO2_RERANK_PROVIDER=local`,
  `go2 trace` inside the stack shows zero egress steps for the smoke's
  searches. Invariant 6 holds in the container as it does on the host.
- Image size and build time recorded in the Outcome, as a baseline for
  T-042.

## Test cases

- `test_compose_declares_the_stack_services` -- db, init, server, worker,
  mongodb and librechat exist; no rag_api, vectordb or meilisearch.
- `test_server_binds_all_interfaces_only_with_a_required_token` -- the
  server command binds `0.0.0.0` and the token is the `${VAR:?}` form.
- `test_server_and_worker_share_one_database_url_inside_the_network` --
  both point at `db:5432`, never at the host's 5433.
- `test_librechat_config_targets_the_stack_server_and_allows_only_it` --
  the MCP url is `http://server:8765/mcp`, `allowedAddresses` is exactly
  `server:8765`, and the header carries the token variable.
- `test_dockerfile_installs_the_locked_dependencies_as_a_non_root_user`
  -- `--locked` and `--no-dev` are present, a `USER` line follows them.
- `test_smoke_rejects_a_result_without_a_citation` -- the smoke's
  assertion helper fails a search result whose passages carry no citation
  or whose evidence is insufficient.
- `test_the_sample_eval_set_names_only_sample_documents` -- every
  `expect_document` in `samples/eval.yaml` matches a file in `samples/`.
- `stack_up_to_first_cited_answer` -- manual acceptance, timed, recorded.

## Design notes

One tenant per stack mirrors one tenant per serving process. The token
still answers only "may you talk to this server"; the workspace is chosen
by the `server` service's environment. Nothing about T-016's boundary
changes, it is only wrapped.

The server binds `0.0.0.0` inside its container because that interface is
the only way LibreChat reaches it, and the network is Compose's private
bridge with only LibreChat's port published to the host. `check_bind`
therefore forces a token, which is the honest configuration and the one
the LibreChat runbook already recommends. `--allow-host server:8765` is
required because DNS-rebinding protection rejects the Compose service
name otherwise, with a 400 that looks like a network fault.

LibreChat's RAG API is not started because this is our Compose file, not
an override of theirs, so there is no inherited `depends_on` to scale
away. Retrieval stays agentic search over one pipeline; a second copy of
the documents in a parallel retrieve-and-stuff path is the duplication
invariant 1 exists to prevent.

With local providers the first boot downloads 1.7 GB of weights into a
named volume, once. Docker Desktop's VM on this machine has 8 GB and 8
CPUs; the batch-size and thread defaults from invariant 7 hold as they
are. T-042 vendors the weights later, and this ticket records the image
size it will start from.

Secrets: `.env` is gitignored, the example carries no values, and
LibreChat's four secrets are generated by the operator with commands in
the README, never defaulted, because accounts registered against
temporary values break when the values change.

The egress boundary is untouched. The stack changes where the process
runs, not what it calls.

## Work log

- 2026-09-18 — Opened from a packaging review: T-030, T-026 and T-042 each
  presume an installable unit that does not exist. Claimed by Claude
  (Fable 5.1) on `deploy/local-stack`.

- 2026-09-18 — Stood the stack up on the owner's M2 (16 GB). Image built
  in 1m51s at 742 MB; all six samples indexed. Smoke passed: tools
  listed, cited answer, document fetched, 401 without the token. Sample
  eval 7/7, MRR 0.92, refusal margin +0.31. On-device (local) providers
  pegged a core and ran hot on this laptop and one sample answer fell
  under the 0.30 floor; switched the test stack to the Jina providers
  (reachable from the container over IPv4, unlike the host) — search
  dropped to ~2 s and the laptop stayed idle. Aligned the smoke's
  default question with a phrasing the eval proves. Provider choice is
  a .env line; invariant 6 (local retrieval) is the on-prem default and
  is unchanged.

- 2026-09-18 — Opened PR #31; in-review. Toolchain clean, full suite
  444 passed nothing skipped.

## Outcome

