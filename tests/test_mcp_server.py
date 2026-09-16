# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""MCP server tests.

The tool schemas are what an MCP client actually sees, so they are asserted
directly: a missing description or a renamed argument breaks the agent without
breaking any other test.
"""

from __future__ import annotations

import hmac
import logging
import socket
import uuid
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.testclient import TestClient

from go2 import mcp_server
from go2.connectors.base import FetchedContent, RemoteFile
from go2.jobs.ingest import ingest_document
from go2.mcp_server import (
    BearerToken,
    MissingTokenError,
    build_http_app,
    check_bind,
    mcp,
    transport_security,
)
from go2.scope import Scope
from go2.storage import repository as repo
from go2.storage.db import connect
from go2.tenancy import resolve_tenant_id
from go2.tools.search import fetch_document, list_documents, search_documents

if TYPE_CHECKING:
    from collections.abc import Iterator, MutableMapping

EXPECTED_TOOLS = {"search_documents", "fetch_document", "list_documents"}


def _database_available() -> bool:
    try:
        with connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


class TestToolSchemas:
    """What the agent sees. No database needed."""

    async def test_the_expected_tools_are_advertised(self) -> None:
        assert {t.name for t in await mcp.list_tools()} == EXPECTED_TOOLS

    async def test_every_tool_has_a_description(self) -> None:
        # An undescribed tool is one the model will not reach for correctly.
        assert all(t.description for t in await mcp.list_tools())

    async def test_search_documents_takes_a_query(self) -> None:
        tool = next(t for t in await mcp.list_tools() if t.name == "search_documents")
        assert "query" in tool.input_schema["properties"]
        assert tool.input_schema.get("required") == ["query"]

    async def test_optional_filters_are_not_required(self) -> None:
        tool = next(t for t in await mcp.list_tools() if t.name == "list_documents")
        assert not tool.input_schema.get("required")

    def test_the_server_requires_grounded_cited_answers(self) -> None:
        # Grounded answers are the whole point; losing any of these would
        # silently turn cited answers into plausible ones. Asserted as three
        # separate properties rather than one keyword, because the wording
        # will change and the requirements should not.
        instructions = (mcp.instructions or "").lower()
        assert "citation" in instructions
        assert "only from recorded documents" in instructions
        # Abstention must be described as correct, not merely permitted.
        assert "correct and expected answer" in instructions
        assert "do not answer from your own knowledge" in instructions

    def test_the_server_explains_the_evidence_gate(self) -> None:
        # The gate is useless if the model does not know to read it.
        instructions = (mcp.instructions or "").lower()
        assert "sufficient_evidence" in instructions
        assert "least irrelevant" in instructions


@pytest.mark.slow
class TestToolsAgainstRealData:
    """The tool functions the MCP layer delegates to."""

    @pytest.fixture
    def indexed(self) -> Iterator[str]:
        """Index one document, then remove it."""
        if not _database_available():  # pragma: no cover - environment dependent
            pytest.skip("no database reachable")

        tenant_id = resolve_tenant_id()
        external_id = f"mcp-{uuid.uuid4()}"
        body = (
            "GLOBEX SUPPLY CONTRACT. Invoice INV-2026-0918. Globex requires "
            "90 days written notice to terminate."
        )
        with connect() as conn:
            scope = Scope(
                tenant_id=tenant_id,
                connection_id=repo.ensure_connection(
                    conn, tenant_id=tenant_id, source="upload", account="mcp-test"
                ),
                source="upload",
            )
            result = ingest_document(
                conn,
                scope=scope,
                remote=RemoteFile(external_id=external_id, title="Globex Supply Contract.txt"),
                content=FetchedContent(data=body.encode(), filename="g.txt", mime=""),
            )
        try:
            yield result.document_id
        finally:
            with connect() as conn:
                repo.delete_document(
                    conn, tenant_id=tenant_id, source="upload", external_id=external_id
                )

    @pytest.mark.usefixtures("indexed")
    def test_search_returns_citable_hits(self) -> None:
        result = search_documents("How much notice does Globex need?", limit=3)
        assert result["passages"]
        assert result["passages"][0]["citation"]
        assert "Globex" in result["passages"][0]["title"]

    @pytest.mark.usefixtures("indexed")
    def test_search_can_be_filtered_by_title(self) -> None:
        result = search_documents("notice", limit=3, title_contains="Nonexistent")
        assert result["passages"] == []
        assert result["sufficient_evidence"] is False

    def test_fetch_returns_the_document_text(self, indexed: str) -> None:
        doc = fetch_document(indexed)
        assert "Globex" in doc["text"]
        assert doc["document_id"] == indexed

    def test_fetch_reports_a_missing_document_instead_of_raising(self) -> None:
        # The agent must be able to recover from a stale id, not crash the turn.
        assert "error" in fetch_document(str(uuid.uuid4()))

    @pytest.mark.usefixtures("indexed")
    def test_list_documents_finds_it_by_metadata(self) -> None:
        # Filtered rather than scanning a top-N listing: this passed only while
        # the developer's index was nearly empty, and started failing once a
        # real corpus pushed the fixture document past the limit.
        titles = [d["title"] for d in list_documents(title_contains="Globex Supply", limit=50)]
        assert "Globex Supply Contract.txt" in titles

    @pytest.mark.usefixtures("indexed")
    def test_list_documents_filters_by_status(self) -> None:
        docs = list_documents(status="indexed", limit=50)
        assert docs
        assert all(d["status"] == "indexed" for d in docs)

    def test_the_server_admits_it_may_not_be_the_only_source(self) -> None:
        # Without this, an empty search reads as "not recorded anywhere", and
        # the model stops instead of checking the tracker or chat history that
        # sits behind another tool.
        instructions = (mcp.instructions or "").lower()
        assert "other sources" in instructions
        assert "does not mean the answer does not exist" in instructions


class TestHttpTransport:
    """Serving over HTTP, for a client that cannot spawn the process itself."""

    def test_the_bind_address_is_always_accepted(self) -> None:
        settings = transport_security(host="127.0.0.1", port=8765, allowed_hosts=[])
        assert "127.0.0.1:8765" in (settings.allowed_hosts or [])

    def test_extra_hosts_are_added_not_substituted(self) -> None:
        # A container reaches the host as host.docker.internal. Replacing the
        # bind address instead of adding to it would break local access.
        settings = transport_security(
            host="127.0.0.1", port=8765, allowed_hosts=["host.docker.internal:8765"]
        )
        allowed = settings.allowed_hosts or []
        assert "127.0.0.1:8765" in allowed
        assert "host.docker.internal:8765" in allowed

    def test_rebinding_protection_stays_on(self) -> None:
        # The easy way to "fix" a 400 is to switch this off, which turns any
        # page the browser visits into a client of this server.
        settings = transport_security(host="127.0.0.1", port=8765, allowed_hosts=[])
        assert settings.enable_dns_rebinding_protection is True

    def test_an_unlisted_host_is_not_accepted(self) -> None:
        settings = transport_security(host="127.0.0.1", port=8765, allowed_hosts=[])
        assert "evil.example:8765" not in (settings.allowed_hosts or [])


TOKEN = "correct-horse-battery-staple"
# The unauthenticated wide bind these tests exist to refuse.
ALL_INTERFACES = "0.0.0.0"  # noqa: S104 -- the bind under test, never one the tests perform.
JSONRPC_HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
}


def _tools_call(name: str, **arguments: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


class TestBearerAuth:
    """The token in front of `go2 serve --http`.

    Driven in-process through the ASGI app rather than over a socket, with the
    search tool replaced by a stub that records whether it ran: the question is
    whether a request gets past the gate, not what retrieval returns.
    """

    @pytest.fixture
    def tool_calls(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []

        def stub(query: str, **kwargs: Any) -> dict[str, Any]:
            calls.append({"query": query, **kwargs})
            return {"passages": [], "sufficient_evidence": False, "guidance": "stub"}

        monkeypatch.setattr(mcp_server, "_search_documents", stub)
        return calls

    @pytest.fixture
    def client(self) -> Iterator[TestClient]:
        app = build_http_app(
            host="127.0.0.1", port=8765, allowed_hosts=[], token=TOKEN, json_response=True
        )
        # base_url sets the Host header; the default `testserver` would be
        # refused by DNS-rebinding protection and test that instead of auth.
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            yield client

    def test_a_request_without_a_token_is_rejected(
        self, client: TestClient, tool_calls: list[dict[str, Any]]
    ) -> None:
        response = client.post(
            "/mcp", json=_tools_call("search_documents", query="anything"), headers=JSONRPC_HEADERS
        )
        assert response.status_code == 401
        # The challenge tells a well-behaved client what is missing.
        assert response.headers["www-authenticate"].startswith("Bearer")
        # ...and the tool never ran: the gate is before the tools, not inside them.
        assert tool_calls == []

    @pytest.mark.parametrize(
        "header",
        [
            "Bearer wrong-token",
            f"Bearer {TOKEN}x",  # a correct prefix is not a match
            f"Bearer {TOKEN[:-1]}",
            f"Basic {TOKEN}",  # right secret, wrong scheme
            TOKEN,  # no scheme at all
        ],
    )
    def test_a_wrong_token_is_rejected(
        self, client: TestClient, tool_calls: list[dict[str, Any]], header: str
    ) -> None:
        response = client.post(
            "/mcp",
            json=_tools_call("search_documents", query="anything"),
            headers={**JSONRPC_HEADERS, "authorization": header},
        )
        assert response.status_code == 401
        assert tool_calls == []

    def test_a_valid_token_reaches_the_tools(
        self, client: TestClient, tool_calls: list[dict[str, Any]]
    ) -> None:
        response = client.post(
            "/mcp",
            json=_tools_call("search_documents", query="what is the notice period?"),
            headers={**JSONRPC_HEADERS, "authorization": f"Bearer {TOKEN}"},
        )
        assert response.status_code == 200
        assert [c["query"] for c in tool_calls] == ["what is the notice period?"]

    def test_the_token_is_compared_in_constant_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A plain `==` returns at the first differing byte, which leaks how
        # much of a guess was right. The comparison has to go through
        # hmac.compare_digest, over digests so length does not leak either.
        seen: list[tuple[bytes, bytes]] = []

        def spy(a: bytes, b: bytes) -> bool:
            seen.append((a, b))
            return hmac.compare_digest(a, b)

        monkeypatch.setattr(mcp_server, "compare_digest", spy)
        gate = BearerToken(_never_called, token=TOKEN)
        scope = {"type": "http", "headers": [(b"authorization", b"Bearer " + TOKEN[:3].encode())]}
        assert gate._authorised(scope) is False  # noqa: SLF001 -- the comparison is the unit under test.
        assert len(seen) == 1
        left, right = seen[0]
        assert len(left) == len(right) == 32  # sha256 digests, not the raw strings
        assert TOKEN.encode() not in (left, right)

    def test_the_token_never_appears_in_logs_or_traces(
        self,
        client: TestClient,
        tool_calls: list[dict[str, Any]],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Traces are written by the tools from their own arguments, so the
        # header cannot reach one unless it reaches the tool; the stub records
        # exactly what the tool was given.
        caplog.set_level(logging.DEBUG)
        wrong = client.post(
            "/mcp",
            json=_tools_call("search_documents", query="q"),
            headers={**JSONRPC_HEADERS, "authorization": "Bearer not-the-token-either"},
        )
        right = client.post(
            "/mcp",
            json=_tools_call("search_documents", query="q"),
            headers={**JSONRPC_HEADERS, "authorization": f"Bearer {TOKEN}"},
        )
        assert wrong.status_code == 401
        assert right.status_code == 200
        assert TOKEN not in caplog.text
        assert "not-the-token-either" not in caplog.text
        assert TOKEN not in wrong.text
        assert "not-the-token-either" not in wrong.text
        assert TOKEN not in right.text
        assert TOKEN not in repr(tool_calls)

    async def test_the_lifespan_scope_passes_through_unauthenticated(self) -> None:
        # Lifespan is the server starting, not a client talking; refusing it
        # would stop the session manager from ever running.
        reached: list[str] = []

        async def inner(scope: Any, _receive: Any, _send: Any) -> None:
            reached.append(scope["type"])

        gate = BearerToken(inner, token=TOKEN)
        await gate({"type": "lifespan"}, _no_messages, _drop)
        assert reached == ["lifespan"]

    async def test_a_websocket_is_closed_not_passed_through(self) -> None:
        # "Not http" must not become the way around the token.
        sent: list[dict[str, Any]] = []

        async def connect() -> dict[str, Any]:
            return {"type": "websocket.connect"}

        async def record(message: MutableMapping[str, Any]) -> None:
            sent.append(dict(message))

        gate = BearerToken(_never_called, token=TOKEN)
        await gate({"type": "websocket", "headers": []}, connect, record)
        assert sent == [{"type": "websocket.close", "code": 1008}]

    def test_a_request_with_no_header_at_all_is_unauthorised(self) -> None:
        gate = BearerToken(_never_called, token=TOKEN)
        assert gate._authorised({"type": "http", "headers": []}) is False  # noqa: SLF001 -- unit under test.

    def test_an_empty_token_cannot_wrap_the_app(self) -> None:
        # An empty expected value would accept an empty header, i.e. nothing.
        with pytest.raises(ValueError, match="non-empty"):
            BearerToken(_never_called, token="")


async def _never_called(_scope: Any, _receive: Any, _send: Any) -> None:  # pragma: no cover
    msg = "the wrapped app must not run"
    raise AssertionError(msg)


async def _no_messages() -> dict[str, Any]:  # pragma: no cover
    msg = "nothing should be received"
    raise AssertionError(msg)


async def _drop(_message: MutableMapping[str, Any]) -> None:
    return


class TestBindCheck:
    """Binding beyond loopback without a token is refused before anything listens."""

    @pytest.mark.parametrize("host", [ALL_INTERFACES, "172.17.0.1", "192.168.1.20", "::"])
    def test_binding_beyond_loopback_without_a_token_refuses_to_start(self, host: str) -> None:
        with pytest.raises(MissingTokenError, match="GO2_HTTP_TOKEN"):
            check_bind(host=host, token="")
        with pytest.raises(MissingTokenError):
            build_http_app(host=host, port=8765, allowed_hosts=[], token="")

    @pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "localhost", "::1"])
    def test_loopback_is_allowed_without_a_token(self, host: str) -> None:
        check_bind(host=host, token="")

    def test_a_name_that_resolves_beyond_loopback_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # /etc/hosts can point `localhost` at the LAN address. The string is
        # not what gets bound; the addresses it resolves to are.
        def lan(*_args: Any, **_kwargs: Any) -> list[tuple[Any, ...]]:
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.20", 0)),
            ]

        monkeypatch.setattr(mcp_server.socket, "getaddrinfo", lan)
        with pytest.raises(MissingTokenError):
            check_bind(host="localhost", token="")

    def test_a_name_that_does_not_resolve_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def unresolvable(*_args: Any, **_kwargs: Any) -> list[tuple[Any, ...]]:
            raise socket.gaierror

        monkeypatch.setattr(mcp_server.socket, "getaddrinfo", unresolvable)
        with pytest.raises(MissingTokenError):
            check_bind(host="no-such-host.invalid", token="")

    def test_a_token_permits_a_wider_bind(self) -> None:
        check_bind(host=ALL_INTERFACES, token=TOKEN)
