# Chat UI

LibreChat in front of Go2Assistant, so questions can be asked from a browser
instead of a terminal.

## Why this shape

LibreChat runs in Docker. `go2` runs on this Mac, against Postgres on port
5433. A stdio MCP server is launched *by* the client, which would mean `go2`,
its Python environment and a route to the database all existing inside
LibreChat's image -- rebuilt on every code change.

Serving over Streamable HTTP inverts that. The server stays here with its
database and the UI is handed an address. It is also what LibreChat recommends
for anything multi-user, and the same transport a hosted deployment needs
later.

One process per workspace, because a tenant is chosen by the environment of
the serving process:

```bash
GO2_TENANT=dawan go2 serve --http --port 8765 --allow-host host.docker.internal:8765
GO2_TENANT=local go2 serve --http --port 8766 --allow-host host.docker.internal:8766
```

Each entry in `librechat.yaml` is named for the tenant it serves. The second is
`local`, not `atmata`, because `local` still holds HaramBlur, Atmata and some
test documents in one workspace -- and that name is the only thing a person
sees when picking a workspace in the UI. Naming it `atmata` would promise an
isolation that does not exist. Rename it when `local` is split.

The server refuses to start if `GO2_TENANT` names a tenant that does not
exist. Tools resolve the tenant per call, so without that check a typo would
serve happily, let the UI discover three tools, and fail once per question
instead of once at startup.

### On a Linux host

`--allow-host` governs which Host header is accepted; it does not change what
address the server binds. The default bind is loopback, and on Docker Desktop
that is reachable because it proxies the container's traffic to the host. On a
Linux host it is not: `host-gateway` resolves to the Docker bridge, and the
bridge cannot reach a listener bound to `127.0.0.1`, so LibreChat's
connections are refused. Bind to the bridge address there:

```bash
BRIDGE=$(docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}')
GO2_TENANT=dawan go2 serve --http --host "$BRIDGE" --port 8765 \
  --allow-host "host.docker.internal:8765" --allow-host "$BRIDGE:8765"
```

Bind to the bridge rather than `0.0.0.0`: there is no authentication in front
of this server, so `0.0.0.0` offers the entire index to anything that can
reach the port, including other machines on the network. Even bound to the
bridge, any container on that host can reach it -- firewall the port, and do
not do this on a shared machine.

`--allow-host` is not optional. DNS-rebinding protection rejects a Host header
it does not recognise, and a container calls this machine
`host.docker.internal` -- without it every request fails with a 400 that looks
like a network problem and is not.

## Setup

```bash
git clone https://github.com/danny-avila/LibreChat.git
cd LibreChat
cp .env.example .env
cp /path/to/Go2Assistant/deploy/librechat/librechat.yaml .
cp /path/to/Go2Assistant/deploy/librechat/docker-compose.override.yml .
echo "ALIBABA_API_KEY=sk-your-key" >> .env
docker compose up -d --scale rag_api=0 --scale vectordb=0 mongodb meilisearch api
```

The `--scale` flags matter. LibreChat ships its own RAG stack -- `rag_api` and a
second pgvector -- and `api` declares `depends_on: rag_api`, so a plain
`docker compose up` starts both. Compose *merges* `depends_on` rather than
replacing it, so the override cannot drop that edge; scaling to zero is what
actually keeps them down. Nothing here needs them: retrieval is agentic search
over one ingestion pipeline, and a parallel retrieve-then-stuff path with its
own copy of the documents is the duplication this architecture exists to avoid.

Then open http://localhost:3080, register an account, and pick
**Qwen (Alibaba, Singapore)**. The `dawan` and `atmata` servers appear in the
tool menu; enable one per conversation.

The API key must be created in the **Singapore** region. Keys are region-bound,
so a Beijing key against the Singapore base URL fails rather than quietly
routing company documents through another jurisdiction.

## Two things that will bite

**`host.docker.internal` is blocked by default.** LibreChat treats any host
ending in `.internal` as an SSRF target, so both servers fail to initialise
with `Domain ... is not allowed` and the UI loads zero tools. The
`mcpSettings.allowedAddresses` block in `librechat.yaml` is the narrow
exemption -- two host:port pairs, protection left on for everything else. Use
`allowedAddresses`, not `allowedDomains`: setting the latter makes it
authoritative and turns the whole thing into a strict whitelist. It is read
once when the registry is built, so it needs a container restart, not a
config reload.

**`Invalid Host header` means the wrong server is on the port.** That error is
this project's own DNS-rebinding check, not LibreChat's. It means something is
listening on the port that was started without the matching `--allow-host` --
usually a stale `go2 serve --http` from an earlier run, which binds 8765 by
default. Check with `pgrep -fl "go2 serve --http"` before changing any config.

**Set the four secrets before registering.** With `CREDS_KEY`, `CREDS_IV`,
`JWT_SECRET` and `JWT_REFRESH_SECRET` unset, LibreChat generates temporary
ones and warns; accounts created against them break when the values later
change. Generate them first, or drop the database and start again as we did.

## Before letting anyone else use it

Two settings that do not matter while you are the only user and matter a lot
when you are not:

- `GO2_PII_REDACT_TOOL_OUTPUT=true` masks PII in passages returned through the
  tools. Off by default because masking your own address out of your own
  contract helps nobody; on when the reader is not the data's owner.
- `go2 serve --http` binds loopback by default. There is no authentication in
  front of it. Binding wider exposes the whole index to anything that can reach
  the port -- put a reverse proxy and auth there first.

## Checking it works

The transport can be verified without the UI:

```bash
go2 search "your question"          # same retrieval, no UI, no model
```

If `go2 search` answers and the UI does not, the problem is LibreChat's
connection, not retrieval. Server logs name the tenant on startup.
