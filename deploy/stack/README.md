# The one-command stack

The whole product on one machine with nothing installed but Docker: the
`go2` MCP server and worker, Postgres with pgvector, and LibreChat as the
browser in front. This is what a client receives, and what a QA run stands
up. The developer-laptop arrangement, with `go2` on the host and LibreChat
in a separate checkout, stays in [`../librechat/`](../librechat/README.md).

One stack serves one workspace. That is the same rule as one serving
process: the token says *may you talk to this server*, and `GO2_TENANT`
says which documents it holds. A second workspace is a second stack.

## First run, with the sample corpus

Docker Desktop, or Docker Engine with the Compose plugin. On a Mac, give
the VM at least 6 GB in Docker Desktop's settings when the providers are
local; the models want about 3 GB resident between the server and the
worker.

```bash
cd deploy/stack
cp .env.example .env
```

Fill in the five required values. `docker compose` refuses to start
without them and names the one that is missing:

```bash
python3 -c 'import secrets; print("GO2_HTTP_TOKEN=" + secrets.token_urlsafe(32))'
echo "CREDS_KEY=$(openssl rand -hex 32)"
echo "CREDS_IV=$(openssl rand -hex 16)"
echo "JWT_SECRET=$(openssl rand -hex 32)"
echo "JWT_REFRESH_SECRET=$(openssl rand -hex 32)"
```

Set `GO2_DASHSCOPE_API_KEY` to an Alibaba Model Studio key created in the
**Singapore** region, so the browser has a model to answer with. Then:

```bash
docker compose --profile samples up -d --build
```

The first run builds the `go2` image, pulls LibreChat and Postgres, and,
with the default local providers, downloads 1.7 GB of model weights into a
volume. It also indexes the six sample files under `samples/` into the
`demo` workspace. Watch it:

```bash
docker compose logs -f seed server
```

When `seed` reports `6 indexed` and `server` reports its address, run the
smoke test from the host. It reads the token and port from `.env`:

```bash
uv run python deploy/stack/smoke.py
```

It lists the tools, asks about the Acme notice period, requires a cited
answer, fetches the cited document, and checks that a request without the
token is refused. Then open <http://localhost:3080>, register the first
account, pick **Qwen (Alibaba, Singapore)**, enable the `go2` server in the
tools menu, and ask:

> What notice period did we agree with Acme, and was it amended?

The answer should cite both the agreement and the amendment. Ask for the
office wifi password and it should say the documents do not say.

## Your own documents

Point `GO2_INGEST_DIR` in `.env` at a folder and name the workspace:

```bash
GO2_TENANT=northwind
GO2_INGEST_DIR=/Users/you/Documents/northwind
```

Restart so the workspace exists, then index the folder. It is mounted
read-only at `/data`:

```bash
docker compose up -d
docker compose run --rm server ingest /data
```

Run without `--profile samples`, so the sample files never land in a real
workspace. Ingestion is the same pipeline the connectors use and skips
unchanged files by hash, so re-running it after edits is cheap. For a large
folder, queue it instead and let the worker drain it:

```bash
docker compose run --rm server ingest --background /data
docker compose logs -f worker
```

`go2 status` and `go2 docs` work the same way:

```bash
docker compose run --rm --no-deps server status
docker compose run --rm --no-deps server docs --by-folder
```

## Retrieval checks

The sample eval set runs inside the stack, where the models and the
database are:

```bash
docker compose run --rm --no-deps server evaluate /app/deploy/stack/samples/eval.yaml
```

For your own workspace, write an eval file by reading your files (the
format is at the top of [`samples/eval.yaml`](samples/eval.yaml)), keep it
under `GO2_INGEST_DIR`, and run it from `/data`. A case per bad answer is
what stops the same failure coming back after the next model or chunking
change.

## From Claude Code or Claude Desktop

The server is published on loopback at `GO2_PORT`. Add to a project's
`.mcp.json`, with the token from `.env` exported in the shell that starts
Claude Code:

```json
{
  "mcpServers": {
    "go2stack": {
      "type": "http",
      "url": "http://127.0.0.1:8770/mcp",
      "headers": { "Authorization": "Bearer ${GO2_HTTP_TOKEN}" }
    }
  }
}
```

This is how an agent runs QA against the same stack a person uses in the
browser: the same three tools, the same workspace, the same token.

## What leaves the machine

With `GO2_EMBEDDING_PROVIDER=local` and `GO2_RERANK_PROVIDER=local`, nothing
during ingestion or search. Generation is the browser's model call to
Alibaba Model Studio in Singapore, and that is the only egress. Check
rather than trust:

```bash
docker compose run --rm --no-deps server trace
```

Every step is listed with an egress mark. Under the Jina providers the
embedding and reranking steps are marked, and every chunk passes the
screening boundary first; `GO2_PII_POLICY` says what happens to sensitive
values there.

## When something is wrong

- **`docker compose up` exits naming a variable.** That variable is empty
  in `.env`. The five required ones are at the top of `.env.example`.
- **The tool menu in LibreChat is empty.** LibreChat discovers MCP servers
  once at start. `docker compose restart librechat` after the server is
  healthy, and check `docker compose logs librechat` for `go2`.
- **`Invalid Host header` or 400 from the server.** A client is calling it
  by a name the `--allow-host` list does not include. Inside the network it
  is `server:8765`; from the host it is `localhost` or `127.0.0.1` on any
  port.
- **401 from the server.** The client's token is not the server's. Both
  read `GO2_HTTP_TOKEN` from `.env`; after changing it, `docker compose up
  -d` recreates both containers.
- **Search says documents are unsearchable under another model.** The
  providers changed after ingestion. Re-run the ingest, or switch back.
- **The worker sits at 0% CPU.** Memory. Docker Desktop's VM is smaller than
  the host; raise it, and leave `GO2_EMBEDDING_BATCH_SIZE` at 4.

## Stop, keep, reset

```bash
docker compose down            # stop; database, models and accounts stay
docker compose down -v         # stop and delete every volume, including the index
```

Nothing in this directory holds data. `.env` holds secrets and is
ignored by git.
