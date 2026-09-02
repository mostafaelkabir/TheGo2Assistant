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
docker compose up -d
```

Then open http://localhost:3080, register an account, and pick
**Qwen (Alibaba, Singapore)**. The `dawan` and `atmata` servers appear in the
tool menu; enable one per conversation.

The API key must be created in the **Singapore** region. Keys are region-bound,
so a Beijing key against the Singapore base URL fails rather than quietly
routing company documents through another jurisdiction.

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
