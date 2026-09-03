# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""MCP server tests.

The tool schemas are what an MCP client actually sees, so they are asserted
directly: a missing description or a renamed argument breaks the agent without
breaking any other test.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from go2.connectors.base import FetchedContent, RemoteFile
from go2.jobs.ingest import ingest_document
from go2.mcp_server import mcp, transport_security
from go2.scope import Scope
from go2.storage import repository as repo
from go2.storage.db import connect
from go2.tenancy import resolve_tenant_id
from go2.tools.search import fetch_document, list_documents, search_documents

if TYPE_CHECKING:
    from collections.abc import Iterator

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
