# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""MCP server exposing retrieval to any MCP client.

Built against MCP SDK 2.x, where ``FastMCP`` was renamed ``MCPServer``.

Deliberately thin: each tool delegates straight to ``go2.tools`` and holds no
logic of its own. That is what lets the same four functions serve this server
today and an in-process agent loop later without a second implementation.

Run with ``go2 serve`` (stdio) or ``go2 serve --http`` (Streamable HTTP).
"""

from __future__ import annotations

import hashlib
import json
from hmac import compare_digest
from typing import TYPE_CHECKING, Any

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

from go2.tools.search import fetch_document as _fetch_document
from go2.tools.search import list_documents as _list_documents
from go2.tools.search import search_documents as _search_documents

mcp = MCPServer(
    "go2assistant",
    instructions=(
        "Answers questions about the user's own documents from OneDrive, Google Drive, "
        "and local uploads.\n\n"
        "Use search_documents for anything about the CONTENT of documents. Prefer full "
        "natural-language questions over keywords -- half the retrieval is semantic. If "
        "the first search misses, rephrase and search again rather than giving up; "
        "several narrow searches beat one broad one.\n\n"
        "Use list_documents for questions about the FILES themselves -- which documents "
        "exist, what came from where, what failed to index. Vector search cannot answer "
        "those.\n\n"
        "Use fetch_document when a snippet is suggestive but incomplete and you need the "
        "surrounding text.\n\n"
        "This assistant answers only from recorded documents. Every claim must come "
        "from a retrieved passage and carry that passage's `citation`, so the user can "
        "check it against the original file.\n\n"
        "search_documents returns `sufficient_evidence` and a `guidance` line. When it "
        "is false, the passages are the least irrelevant text in the index rather than "
        "an answer: say the documents do not cover the question. Do not assemble an "
        "answer from weak passages, and do not answer from your own knowledge even when "
        "you are confident -- an unsourced answer here is a defect, not a helpful "
        'extra. "The documents do not say" is a correct and expected answer.\n\n'
        "This index covers ingested files only. It is frequently one of several "
        "sources -- a project may also have a tracker, a wiki, or a chat history "
        "reachable through other tools. An empty result here means the answer is not "
        "in the indexed files; it does not mean the answer does not exist. Say which "
        "of the two you mean, and check the other sources available to you before "
        "concluding something was never recorded."
    ),
)


@mcp.tool()
def search_documents(
    query: str,
    limit: int = 8,
    source: str | None = None,
    title_contains: str | None = None,
) -> dict[str, Any]:
    """Search the user's documents for passages answering a question.

    Returns `sufficient_evidence`, a `guidance` line, and the passages. When
    `sufficient_evidence` is false the passages are the least irrelevant text
    in the index, not an answer -- do not build one from them, and do not fall
    back on your own knowledge. Follow `guidance`.

    Args:
        query: A natural-language question. Full sentences retrieve better
            than keywords.
        limit: Maximum passages to return.
        source: Restrict to one connector: 'gdrive', 'onedrive', or 'upload'.
        title_contains: Restrict to documents whose title contains this text.
    """
    return _search_documents(query, limit=limit, source=source, title_contains=title_contains)


@mcp.tool()
def fetch_document(document_id: str, page: int | None = None) -> dict[str, Any]:
    """Read the full text of one document.

    Args:
        document_id: An id returned by search_documents.
        page: Restrict to a single page number, if the document has pages.
    """
    return _fetch_document(document_id, page=page)


@mcp.tool()
def list_documents(
    source: str | None = None,
    title_contains: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List indexed documents by metadata rather than by content.

    Use for questions about which files exist, where they came from, or which
    failed to index -- things no passage search can answer.

    Args:
        source: Restrict to one connector: 'gdrive', 'onedrive', or 'upload'.
        title_contains: Restrict to titles containing this text.
        status: Restrict to 'indexed', 'pending', 'failed', or 'skipped'.
        limit: Maximum documents to return.
    """
    return _list_documents(source=source, title_contains=title_contains, status=status, limit=limit)


def main() -> None:
    """Run the server on stdio, for a client that launches it as a subprocess."""
    mcp.run()


def transport_security(
    *, host: str, port: int, allowed_hosts: list[str]
) -> TransportSecuritySettings:
    """Host headers this server will answer to.

    Kept separate because getting it wrong fails in a misleading way: DNS
    rebinding protection returns 400 for an unrecognised Host, which reads as a
    network fault rather than a policy decision.
    """
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[f"{host}:{port}", *allowed_hosts],
        allowed_origins=["*"],
    )


# Interfaces only this machine can reach. Anything else is "beyond loopback"
# and needs a token before the server will bind to it.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class MissingTokenError(RuntimeError):
    """Raised when ``--host`` reaches beyond this machine and no token is set."""

    def __init__(self, host: str) -> None:
        """Name the interface and the fix."""
        super().__init__(
            f"refusing to bind {host}: anything that can reach the port would read "
            f"every document. Set GO2_HTTP_TOKEN to a secret (for example the output "
            f"of `python -c 'import secrets; print(secrets.token_urlsafe(32))'`) and "
            f"give the same value to the client, or bind 127.0.0.1."
        )


def check_bind(*, host: str, token: str) -> None:
    """Refuse a bind that would serve the index unauthenticated.

    Loopback is allowed without a token because only this machine can reach
    it. Any other interface -- a Docker bridge, ``0.0.0.0``, a LAN address --
    is refused, since binding it without a token is the failure the whole
    ticket exists to prevent.

    Raises:
        MissingTokenError: If ``host`` is not loopback and ``token`` is empty.
    """
    if host not in LOOPBACK_HOSTS and not token:
        raise MissingTokenError(host)


def _digest(value: bytes) -> bytes:
    return hashlib.sha256(value).digest()


class BearerToken:
    """ASGI middleware that answers 401 unless the request carries the token.

    Auth answers *may you talk to this server*, nothing more. The tenant is
    still chosen by the serving process, so a token is scoped to whatever that
    process serves and never chooses a workspace itself; conflating the two
    would let a token name a tenant, which is how one client reads another's
    documents.

    The comparison goes through ``hmac.compare_digest`` over fixed-length
    digests, so neither the token's length nor how many leading bytes matched
    shows in the response time. The presented value is never logged, echoed
    or stored: the 401 body says only that a bearer token is required.
    """

    def __init__(self, app: ASGIApp, *, token: str) -> None:
        """Wrap ``app`` so every HTTP request must present ``token``."""
        if not token:
            msg = "BearerToken needs a non-empty token; use the app unwrapped for none"
            raise ValueError(msg)
        self._app = app
        self._expected = _digest(token.encode())

    def _authorised(self, scope: Scope) -> bool:
        header = next(
            (value for name, value in scope.get("headers", []) if name == b"authorization"),
            b"",
        )
        scheme, _, presented = header.strip().partition(b" ")
        if scheme.lower() != b"bearer":
            return False
        return compare_digest(_digest(presented.strip()), self._expected)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass lifespan and authorised HTTP through; refuse everything else.

        Only the lifespan scope is exempt, because it is the server starting,
        not a client talking. A websocket scope is closed rather than passed
        through: nothing here serves websockets today, and "not http" must not
        become the way around the token if something ever does.
        """
        if scope["type"] == "lifespan" or (scope["type"] == "http" and self._authorised(scope)):
            await self._app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await receive()  # the connect frame; a close before it is a protocol error
            await send({"type": "websocket.close", "code": 1008})  # policy violation
            return
        body = json.dumps({"error": "unauthorized", "detail": "a bearer token is required"})
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b'Bearer realm="go2assistant"'),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body.encode()})


def build_http_app(
    *,
    host: str,
    port: int,
    allowed_hosts: list[str],
    token: str,
    json_response: bool = False,
) -> ASGIApp:
    """The ASGI application ``go2 serve --http`` runs.

    Separate from :func:`run_http` so a test can drive it in-process, without
    a socket. The token check wraps the whole application, so an
    unauthenticated request is refused before the transport, the Host check
    or any tool sees it.

    Args:
        host: Interface the server will bind; also the Host header it accepts.
        port: Port it will bind.
        allowed_hosts: Extra Host headers to accept.
        token: Bearer token every request must carry. Empty means none, which
            :func:`check_bind` allows only on loopback.
        json_response: Answer with plain JSON rather than an event stream.
    """
    check_bind(host=host, token=token)
    app: ASGIApp = mcp.streamable_http_app(
        host=host,
        # Stateless: each request stands alone, so several chat sessions can
        # use one server without sharing or outliving a session.
        stateless_http=True,
        json_response=json_response,
        transport_security=transport_security(host=host, port=port, allowed_hosts=allowed_hosts),
    )
    if token:
        app = BearerToken(app, token=token)
    return app


def run_http(*, host: str, port: int, allowed_hosts: list[str], token: str) -> None:
    """Run the server over Streamable HTTP, for a client that cannot spawn it.

    A containerised chat UI is the case that needs this. Under stdio the client
    launches ``go2 serve`` itself, which requires the binary, the Python
    environment and a route to Postgres to exist wherever the client runs --
    inside its image, not on this machine. Serving over HTTP inverts that: the
    server stays here with its database, and the client is given an address.

    Args:
        host: Interface to bind. Defaults to loopback; binding wider exposes
            the whole index to anything that can reach the port, so it is
            refused unless ``token`` is set.
        port: Port to bind.
        allowed_hosts: Host headers to accept, beyond ``host:port`` itself.
            DNS-rebinding protection rejects unrecognised Host headers, and a
            container reaching the Mac calls it ``host.docker.internal``, so
            that name has to be named explicitly or every request 400s.
        token: Bearer token every request must present; empty for none.

    Raises:
        MissingTokenError: If ``host`` is not loopback and ``token`` is empty.
    """
    import uvicorn  # noqa: PLC0415 -- a server dependency; keep it out of stdio and the CLI.

    app = build_http_app(host=host, port=port, allowed_hosts=allowed_hosts, token=token)
    config = uvicorn.Config(app, host=host, port=port, log_level=mcp.settings.log_level.lower())
    anyio.run(uvicorn.Server(config).serve)


if __name__ == "__main__":
    main()
