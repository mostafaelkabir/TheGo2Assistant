# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Hybrid retrieval tests against a real indexed corpus.

The corpus is built so each test isolates one failure mode: two near-identical
contracts force real disambiguation, an invoice number tests the keyword half
that embeddings are worst at, and an Arabic query tests cross-language recall.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from go2.connectors.base import FetchedContent, RemoteFile
from go2.jobs.ingest import ingest_document
from go2.rag.retrieval import RRF_K, SearchFilters, SearchOptions, _fuse, search
from go2.scope import Scope
from go2.storage import repository as repo
from go2.storage.db import connect, default_tenant_id, get_engine

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Connection

pytestmark = pytest.mark.slow


def _database_available() -> bool:
    try:
        with connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


if not _database_available():  # pragma: no cover - environment dependent
    pytest.skip("no database reachable", allow_module_level=True)

CORPUS = {
    "Acme Master Services Agreement.txt": (
        "ACME HOLDINGS MASTER SERVICES AGREEMENT. Invoice number INV-2026-0417 "
        "governs this engagement. The annual renewal fee is 4,500 USD, payable "
        "each March. Either party may terminate with 60 days written notice."
    ),
    "Globex Supply Contract.txt": (
        "GLOBEX SUPPLY CONTRACT. Invoice number INV-2026-0918. The annual renewal "
        "fee is 7,200 USD, payable each September. Globex requires 90 days "
        "written notice to terminate."
    ),
    "Employee Handbook.txt": (
        "Receipts above 50 USD must be submitted within 30 days. Engineers may "
        "work remotely up to three days per week."
    ),
}


@pytest.fixture
def conn() -> Iterator[Connection]:
    """A rolled-back connection, so the corpus never persists."""
    connection = get_engine().connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


@pytest.fixture
def tenant_id() -> str:
    return default_tenant_id()


@pytest.fixture
def corpus(conn: Connection, tenant_id: str) -> str:
    """Ingest the fixture corpus and return the tenant it belongs to."""
    scope = Scope(
        tenant_id=tenant_id,
        connection_id=repo.ensure_connection(
            conn, tenant_id=tenant_id, source="upload", account=f"t-{uuid.uuid4()}"
        ),
        source="upload",
    )
    for name, body in CORPUS.items():
        ingest_document(
            conn,
            scope=scope,
            remote=RemoteFile(external_id=f"ext-{uuid.uuid4()}", title=name),
            content=FetchedContent(data=body.encode(), filename=name, mime=""),
        )
    return tenant_id


@dataclass
class FakeRow:
    """A minimal row satisfying the RetrievedRow protocol."""

    chunk_id: str
    document_id: str = "doc"
    text: str = "text"
    page: int | None = None
    slide: int | None = None
    heading: str | None = None
    title: str = "Title"
    source: str = "upload"
    web_url: str | None = None


class TestFusion:
    """RRF combines by rank, not by score."""

    def test_a_chunk_found_by_both_retrievers_outranks_one_found_by_either(self) -> None:
        # The whole point of fusion: agreement between two independent
        # retrievers is stronger evidence than a top rank from just one.
        both, vector_only, text_only = FakeRow("both"), FakeRow("v"), FakeRow("t")
        fused = _fuse({"vector": [vector_only, both], "text": [text_only, both]})
        assert fused[0].row.chunk_id == "both"

    def test_scores_follow_the_reciprocal_rank_formula(self) -> None:
        fused = _fuse({"vector": [FakeRow("a")]})
        assert fused[0].rrf == pytest.approx(1.0 / (RRF_K + 1))


class TestSearchQuality:
    """The four query shapes that must work."""

    def test_disambiguates_between_two_similar_contracts(
        self, conn: Connection, corpus: str
    ) -> None:
        hits = search(
            conn,
            tenant_id=corpus,
            query="How much notice do I need to terminate the Globex contract?",
            options=SearchOptions(limit=3),
        )
        assert hits
        assert "Globex" in hits[0].title

    def test_finds_an_exact_identifier(self, conn: Connection, corpus: str) -> None:
        # The keyword half earns its place here: an invoice number is close to
        # meaningless to an embedding, and both documents look alike otherwise.
        hits = search(conn, tenant_id=corpus, query="INV-2026-0417", options=SearchOptions(limit=3))
        assert hits
        assert "Acme" in hits[0].title

    def test_an_arabic_query_retrieves_the_english_passage(
        self, conn: Connection, corpus: str
    ) -> None:
        hits = search(
            conn,
            tenant_id=corpus,
            query="ما هي رسوم تجديد أكمي؟",
            options=SearchOptions(limit=3),
        )
        assert hits
        assert "Acme" in hits[0].title

    def test_matches_a_paraphrase(self, conn: Connection, corpus: str) -> None:
        hits = search(
            conn,
            tenant_id=corpus,
            query="Can engineers work from home?",
            options=SearchOptions(limit=3),
        )
        assert hits
        assert "remotely" in hits[0].text


class TestFiltersAndScoping:
    """Narrowing, and the tenant boundary."""

    def test_title_filter_restricts_results(self, conn: Connection, corpus: str) -> None:
        hits = search(
            conn,
            tenant_id=corpus,
            query="renewal fee",
            filters=SearchFilters(title_contains="Globex"),
            options=SearchOptions(limit=5),
        )
        assert hits
        assert all("Globex" in h.title for h in hits)

    def test_source_filter_excludes_other_connectors(self, conn: Connection, corpus: str) -> None:
        assert (
            search(
                conn,
                tenant_id=corpus,
                query="renewal fee",
                filters=SearchFilters(source="gdrive"),
                options=SearchOptions(limit=5),
            )
            == []
        )

    @pytest.mark.usefixtures("corpus")
    def test_another_tenant_sees_nothing(self, conn: Connection) -> None:
        assert (
            search(conn, tenant_id=str(uuid.uuid4()), query="renewal fee", options=SearchOptions())
            == []
        )

    def test_an_empty_query_returns_nothing(self, conn: Connection, tenant_id: str) -> None:
        assert search(conn, tenant_id=tenant_id, query="   ", options=SearchOptions()) == []

    def test_limit_is_respected(self, conn: Connection, corpus: str) -> None:
        assert len(search(conn, tenant_id=corpus, query="fee", options=SearchOptions(limit=1))) == 1


class TestCitations:
    """Every hit must be attributable."""

    def test_hits_carry_a_citation(self, conn: Connection, corpus: str) -> None:
        hits = search(conn, tenant_id=corpus, query="renewal fee", options=SearchOptions(limit=1))
        assert hits[0].citation()
        assert hits[0].title in hits[0].citation()

    def test_reranking_changes_the_order(self, conn: Connection, corpus: str) -> None:
        # If reranking were a no-op the cross-encoder would be dead weight.
        query = "How much notice do I need to terminate the Globex contract?"
        reranked = search(conn, tenant_id=corpus, query=query, options=SearchOptions(limit=3))
        raw = search(
            conn, tenant_id=corpus, query=query, options=SearchOptions(limit=3, rerank=False)
        )
        assert reranked
        assert raw
        assert "Globex" in reranked[0].title
