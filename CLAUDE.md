# Go2Assistant — working agreement

An assistant that answers questions about files in OneDrive and Google Drive.
Architecture and rationale: `docs/architecture.md`. Read it before changing structure.
What is planned and in what order: `docs/roadmap.md`. What exactly is being
built, by whom, and whether it is done: `backlog/`.

## Non-negotiable: no code without a ticket

Every change starts from a ticket in `backlog/tickets/` and ends by updating
it. The full lifecycle and the rules are in `backlog/README.md`; the short
version:

1. `go2 backlog` lists what is `ready`. Read the ticket file before starting.
   If the work has no ticket, write one first (`go2 backlog new`) with a
   problem statement, a definition of scope, success metrics and named test
   cases. Empty sections are refused by `go2 backlog check`.
2. Claim it: `status: in-progress`, `owner:`, `branch:`. Commit that first,
   so a second agent fetching the branch list sees the claim.
3. When the PR opens: `status: in-review`, `pr:`. The PR body names the id.
4. When the PR merges: `status: done`, `closed:`, and a written `## Outcome`
   with the success metrics as measured. Commit that to `main`.
5. Run `go2 backlog index` after every ticket edit and commit `BACKLOG.md`
   with it. The fast tests fail on a stale index or a malformed ticket.

A fix small enough to describe fully in its commit message does not need a
ticket. "Small enough" means a reviewer would not ask why.

## Non-negotiable: run the toolchain after every change

After any edit, run all three and fix everything they report:

```bash
uv run ruff format . && uv run ruff check --fix . && uv run pyrefly check
```

- **Do not suppress to get green.** `# noqa` and `# type: ignore` require an inline
  comment justifying why the rule is wrong *here*. A bare suppression is a bug.
- **Do not add rules to `ignore`** in `pyproject.toml`. It holds exactly two entries
  (`COM812`, `ISC001`), both mandated by Ruff for formatter compatibility. That list
  is closed.
- Type annotations are required on every function signature, including tests.

## Architectural invariants

These are load-bearing. Changing one is a design decision, not a refactor.

1. **Agentic search, not single-shot RAG.** Retrieval is exposed as tools; the model
   drives the loop. Never add a "retrieve top-k then stuff the prompt" path.
2. **One ingestion pipeline.** Every source — upload, Google Drive, OneDrive — goes
   through the same parse → chunk → embed flow. No per-connector ingestion logic.
3. **Spreadsheets are never chunked as prose.** Index a per-sheet summary; keep the
   real table and serve rows via `query_spreadsheet`. Prose-chunking a sheet destroys
   the numbers the question is about.
4. **Providers sit behind interfaces.** Model ids live in `config.py`, never inline.
   Connectors implement `go2.connectors.base.Connector`.
5. **`tenant_id` on every table and every query.** Single tenant today, multi-tenant
   later without a migration.
6. **Retrieval stays local.** Embeddings and reranking run on-device. Only generation
   calls out. A cheap cloud CPU is slower than an M2, so hosting is not a fix.
7. **Bound every model batch.** fastembed defaults to `batch_size=256`, which on CPU
   buys no throughput and cost 24 GB resident on a 16 GB machine — the process
   swap-thrashed instead of computing. Throughput is flat from batch 1 to 4.
8. **Every bad answer becomes an eval case.** Retrieval regressions are silent --
   the system keeps returning confident passages, just the wrong ones. `go2 evaluate`
   is the only thing that catches that; a fix without a case will regress unnoticed.
9. **Hybrid search, never vector-only.** Exact identifiers (invoice numbers, client
   names) are what embeddings are worst at and what people search for. Vector and
   full-text results are fused by Reciprocal Rank Fusion, then reranked.

## Data handling

- **One egress boundary.** Everything leaving the machine goes through
  `go2.security.guard.screen`. A new call path that reaches a third party
  without it is a bug, not a shortcut — a control spread across call sites is
  one the next code path silently bypasses.
- PII detectors are validated (Luhn, mod-97) rather than pattern-only. Precision
  over recall: a redactor that fires on ordinary content gets switched off, and
  a switched-off control protects nothing.

- Alibaba Model Studio, **Singapore endpoint only**. Beijing is a different data
  jurisdiction for company documents.
- OAuth refresh tokens are Fernet-encrypted at rest. Never log a token or file content.

## Commands

```bash
go2 migrate                         # apply SQL migrations
go2 ingest ~/Documents/work         # index a folder in the foreground
go2 ingest ~/big-folder --background # queue it instead
go2 worker                          # drain the queue
go2 jobs                            # what is queued
go2 search "your question"          # check retrieval from the terminal
go2 evaluate                        # run eval/questions.yaml, report rank + MRR
go2 trace                           # what each component did with the last requests
go2 docs                            # every ingested file
go2 docs --by-folder                # ...grouped by directory
go2 status                          # what is indexed, and which model embedded it
go2 serve                           # MCP server on stdio
go2 serve --http --port 8765        # ...over Streamable HTTP, for a chat UI
go2 backlog                         # tickets ready to pick up
go2 backlog check                   # validate tickets and the index (CI runs this)
go2 backlog index                   # regenerate backlog/BACKLOG.md
go2 backlog new "title" --phase 1-drive

uv run pytest                       # full suite
uv run pytest -m "not slow"         # skip those needing a model or a database
```

`go2` is installed as a uv tool (`uv tool install --editable .`), so it runs
from any directory. Configuration is read from `~/.config/go2/.env` first, then
a project-local `.env` which overrides it — a bare `.env` alone would resolve
against whatever directory the command was typed in, and silently fall back to
defaults everywhere else. **The MCP server does not pick up code changes** — restart
Claude Code after editing anything the tools touch.

The dev database is Homebrew `postgresql@17` on **port 5433** (5432 is an older
`postgresql@15`). `docker-compose.yml` targets the same port if you prefer Docker.
