# Go2Assistant — working agreement

An assistant that answers questions about files in OneDrive and Google Drive.
Architecture and rationale: `docs/architecture.md`. Read it before changing structure.

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
8. **Hybrid search, never vector-only.** Exact identifiers (invoice numbers, client
   names) are what embeddings are worst at and what people search for. Vector and
   full-text results are fused by Reciprocal Rank Fusion, then reranked.

## Data handling

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
go2 status                          # what is indexed
go2 serve                           # MCP server on stdio

uv run pytest                       # full suite
uv run pytest -m "not slow"         # skip the model-loading ones
```

`go2` is installed as a uv tool (`uv tool install --editable .`), so it runs
from any directory. **The MCP server does not pick up code changes** — restart
Claude Code after editing anything the tools touch.

The dev database is Homebrew `postgresql@17` on **port 5433** (5432 is an older
`postgresql@15`). `docker-compose.yml` targets the same port if you prefer Docker.
