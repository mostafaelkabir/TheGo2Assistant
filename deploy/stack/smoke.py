# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Prove a running stack answers: tools listed, a cited answer, a stranger refused.

Three checks, in the order a client meets them, against the MCP server over
Streamable HTTP with the stack's bearer token:

1. The three tools are advertised.
2. A question about the sample corpus comes back with ``sufficient_evidence``
   and a citation naming the expected document, and that document fetches.
3. A request without the token is refused with 401 before any tool runs.

From the host, reading the token and port from ``.env`` beside this file::

    uv run python deploy/stack/smoke.py

Inside the stack, where the server is called ``server``::

    docker compose run --rm --no-deps server python deploy/stack/smoke.py --url http://server:8765/mcp

The exit status is non-zero on the first miss, with the reason, so the same
script serves T-026's fresh-host check and the QA runner.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Annotated, Any

# The HTTP client the MCP SDK itself uses and installs; the session needs one
# of these, not the project's httpx, to carry the bearer header.
import httpx2
import typer
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent

EXPECTED_TOOLS = frozenset({"search_documents", "fetch_document", "list_documents"})
DEFAULT_PORT = "8770"
DEFAULT_QUESTION = "What notice period did we agree with Acme for termination?"
DEFAULT_TITLE = "Acme"
HTTP_UNAUTHORIZED = 401
ENV_FILE = Path(__file__).with_name(".env")


class SmokeError(Exception):
    """One check did not hold. The message says which, and what came back."""


def read_env_file(path: Path) -> dict[str, str]:
    """Read ``KEY=value`` lines from a dotenv file, ignoring comments and blanks.

    Args:
        path: The file. A missing file reads as empty, so the script still
            runs with explicit flags where no ``.env`` exists.

    Returns:
        The keys and values, quotes stripped.
    """
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def check_tools(names: set[str]) -> None:
    """Every tool the server is meant to advertise must be present.

    Raises:
        SmokeError: Naming the missing tools and the ones advertised.
    """
    missing = EXPECTED_TOOLS - names
    if missing:
        msg = f"tools missing: {sorted(missing)}; advertised: {sorted(names)}"
        raise SmokeError(msg)


def check_search(result: dict[str, Any], *, expected_title: str) -> str:
    """Return the id of a cited passage from the expected document.

    A search that returns passages without a citation is the failure the
    product exists to prevent, so it is a miss even when the text looks
    right. So is a refusal: the sample question is one the corpus answers.

    Args:
        result: What ``search_documents`` returned.
        expected_title: A substring of the title a citation must name.

    Returns:
        The ``document_id`` of the first cited passage from that document.

    Raises:
        SmokeError: When the evidence gate refused, no passage carries a
            citation, or none cites the expected document.
    """
    if not result.get("sufficient_evidence"):
        msg = (
            f"evidence gate refused: best_score={result.get('best_score')} "
            f"guidance={result.get('guidance')!r}"
        )
        raise SmokeError(msg)
    passages = result.get("passages") or []
    cited = [p for p in passages if p.get("citation")]
    if not cited:
        msg = f"{len(passages)} passages returned and none carries a citation"
        raise SmokeError(msg)
    wanted = expected_title.casefold()
    for passage in cited:
        if wanted in str(passage.get("title", "")).casefold():
            return str(passage["document_id"])
    msg = f"no citation names {expected_title!r}; cited: {[p['citation'] for p in cited]}"
    raise SmokeError(msg)


def check_fetch(result: dict[str, Any]) -> None:
    """The cited document must fetch with text.

    Raises:
        SmokeError: On an error result or an empty body.
    """
    if "error" in result:
        msg = f"fetch failed: {result['error']}"
        raise SmokeError(msg)
    if not str(result.get("text", "")).strip():
        msg = "fetched document has no text"
        raise SmokeError(msg)


def payload(result: object) -> dict[str, Any]:
    """The tool's return value, whichever way the transport carried it.

    Raises:
        SmokeError: When the call errored or the body is not a mapping.
    """
    if not isinstance(result, CallToolResult):
        msg = f"unexpected tool result type {type(result).__name__}"
        raise SmokeError(msg)
    text = "".join(c.text for c in result.content if isinstance(c, TextContent))
    if result.is_error:
        msg = f"tool call errored: {text[:300]}"
        raise SmokeError(msg)
    if isinstance(result.structured_content, dict):
        return result.structured_content
    loaded = json.loads(text) if text else {}
    if not isinstance(loaded, dict):
        msg = f"tool returned {type(loaded).__name__}, expected an object"
        raise SmokeError(msg)
    return loaded


async def run(*, url: str, token: str, question: str, expected_title: str) -> list[str]:
    """Run the three checks and return one line of evidence per step.

    Raises:
        SmokeError: On the first check that does not hold.
    """
    lines: list[str] = []
    timeout = httpx2.Timeout(30.0, read=300.0)
    headers = {"Authorization": f"Bearer {token}"}
    async with (
        httpx2.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as http,
        streamable_http_client(url, http_client=http) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        names = {tool.name for tool in (await session.list_tools()).tools}
        check_tools(names)
        lines.append(f"tools advertised: {', '.join(sorted(names))}")

        found = payload(await session.call_tool("search_documents", {"query": question}))
        document_id = check_search(found, expected_title=expected_title)
        best = next(p for p in found["passages"] if p["document_id"] == document_id)
        lines.append(f"cited: {best['citation']} (score {best['score']})")

        fetched = payload(await session.call_tool("fetch_document", {"document_id": document_id}))
        check_fetch(fetched)
        lines.append(f"fetched: {fetched['title']} ({len(fetched['text'])} chars)")

    async with httpx2.AsyncClient(timeout=timeout) as http:
        response = await http.post(
            url,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )
    if response.status_code != HTTP_UNAUTHORIZED:
        msg = f"a request without the token got {response.status_code}, expected 401"
        raise SmokeError(msg)
    lines.append("without the token: 401")
    return lines


def main(
    url: Annotated[
        str, typer.Option(help="The MCP endpoint. Default: loopback on GO2_PORT from .env.")
    ] = "",
    token: Annotated[
        str, typer.Option(envvar="GO2_HTTP_TOKEN", help="Bearer token. Default: from .env.")
    ] = "",
    question: Annotated[str, typer.Option(help="A question the corpus answers.")] = (
        DEFAULT_QUESTION
    ),
    expect_title: Annotated[
        str, typer.Option(help="Substring of the document title a citation must name.")
    ] = DEFAULT_TITLE,
) -> None:
    """Check that a running stack lists its tools, cites an answer and refuses a stranger."""
    env = read_env_file(ENV_FILE)
    url = url or f"http://127.0.0.1:{env.get('GO2_PORT', DEFAULT_PORT)}/mcp"
    token = token or env.get("GO2_HTTP_TOKEN", "")
    if not token:
        typer.echo(f"no token: pass --token, set GO2_HTTP_TOKEN, or fill {ENV_FILE}", err=True)
        raise typer.Exit(code=2)

    started = time.perf_counter()
    typer.echo(f"smoke against {url}")
    try:
        for line in asyncio.run(
            run(url=url, token=token, question=question, expected_title=expect_title)
        ):
            typer.echo(f"  ok   {line}")
    except SmokeError as exc:
        typer.echo(f"  FAIL {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"smoke passed in {time.perf_counter() - started:.1f}s")


if __name__ == "__main__":
    typer.run(main)
