# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""End-to-end ingestion against the real database and the real embedding model.

Nothing is stubbed: genuine file bytes go through extraction, chunking, local
Qwen3 embedding, and pgvector storage. This is the test that would catch a
dimension mismatch, a bad vector literal, or a broken cascade -- none of which
a unit test with fakes can see.

Skipped automatically when no database is reachable.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from go2.connectors.base import FetchedContent, RemoteFile
from go2.extraction.registry import content_hash
from go2.jobs.ingest import IngestResult, ingest_document
from go2.rag.embedding import embed_query
from go2.scope import Scope
from go2.storage import repository as repo
from go2.storage.db import connect, default_tenant_id, get_engine
from go2.storage.repository import _vector_literal

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Connection

pytestmark = pytest.mark.slow

SOURCE = "gdrive"

# Malformed input across every supported parser, each raising a different
# exception type from a different library.
CORRUPT_FILES = [
    ("garbage.pdf", b"%PDF-1.7\n" + b"\xde\xad\xbe\xef" * 200),
    ("empty.pdf", b""),
    ("notzip.docx", b"this is not a zip file at all"),
    ("notzip.xlsx", b"this is not a zip file at all"),
    ("notzip.pptx", b"this is not a zip file at all"),
    ("truncated.docx", b"PK\x03\x04" + b"\x00" * 40),
]
EXPECTED_BUDGET_SHEETS = 1
EXPECTED_SCANNED_PAGES = 2


def _database_available() -> bool:
    try:
        with connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


pytest.importorskip("sqlalchemy")
if not _database_available():  # pragma: no cover - environment dependent
    pytest.skip("no database reachable", allow_module_level=True)


@pytest.fixture
def tenant_id() -> str:
    return default_tenant_id()


@pytest.fixture
def conn() -> Iterator[Connection]:
    """A connection whose work is rolled back, so tests leave no residue."""
    connection = get_engine().connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


@pytest.fixture
def connection_id(conn: Connection, tenant_id: str) -> str:
    return repo.ensure_connection(
        conn, tenant_id=tenant_id, source=SOURCE, account=f"test-{uuid.uuid4()}"
    )


def _remote(name: str, mime: str = "") -> RemoteFile:
    return RemoteFile(external_id=f"ext-{uuid.uuid4()}", title=name, mime=mime)


def _ingest(
    conn: Connection, tenant_id: str, connection_id: str, data: bytes, name: str
) -> IngestResult:
    remote = _remote(name)
    return ingest_document(
        conn,
        scope=Scope(tenant_id=tenant_id, connection_id=connection_id, source=SOURCE),
        remote=remote,
        content=FetchedContent(data=data, filename=name, mime=""),
    )


class TestHappyPath:
    """A document goes in and comes out searchable."""

    def test_a_pdf_becomes_indexed_chunks_with_real_vectors(
        self, conn: Connection, tenant_id: str, connection_id: str, pdf_with_text: bytes
    ) -> None:
        result = _ingest(conn, tenant_id, connection_id, pdf_with_text, "Acme Contract.pdf")

        assert result.indexed
        assert result.chunks > 0

        row = conn.execute(
            text("""
                SELECT embedding IS NOT NULL AS has_vector,
                       vector_dims(embedding) AS dims,
                       page
                  FROM chunks WHERE document_id = :d ORDER BY ordinal LIMIT 1
            """),
            {"d": result.document_id},
        ).one()
        assert row.has_vector
        assert row.dims == 1024
        assert row.page == 1

    def test_full_text_index_is_populated(
        self, conn: Connection, tenant_id: str, connection_id: str, pdf_with_text: bytes
    ) -> None:
        # Hybrid search needs the tsvector as much as the embedding; the
        # generated column would silently stay empty if the text column moved.
        result = _ingest(conn, tenant_id, connection_id, pdf_with_text, "Acme Contract.pdf")
        matches = conn.execute(
            text("""
                SELECT count(*) FROM chunks
                 WHERE document_id = :d AND tsv @@ plainto_tsquery('simple', 'renewal')
            """),
            {"d": result.document_id},
        ).scalar_one()
        assert matches > 0

    def test_a_docx_is_indexed(
        self, conn: Connection, tenant_id: str, connection_id: str, docx_bytes: bytes
    ) -> None:
        result = _ingest(conn, tenant_id, connection_id, docx_bytes, "Terms.docx")
        assert result.indexed
        assert result.chunks > 0

    def test_vectors_are_queryable_by_cosine_distance(
        self, conn: Connection, tenant_id: str, connection_id: str, pdf_with_text: bytes
    ) -> None:
        # Proves the stored literal is a real vector the index can operate on,
        # not a string that merely inserted without error.

        result = _ingest(conn, tenant_id, connection_id, pdf_with_text, "Acme Contract.pdf")
        query = _vector_literal(embed_query("What is the renewal fee?"))
        distance = conn.execute(
            text("""
                SELECT embedding <=> CAST(:q AS vector) AS distance
                  FROM chunks WHERE document_id = :d ORDER BY distance LIMIT 1
            """),
            {"q": query, "d": result.document_id},
        ).scalar_one()
        assert 0.0 <= float(distance) <= 2.0


class TestNonProseDocuments:
    """Spreadsheets and scans take different paths through the pipeline."""

    def test_a_spreadsheet_produces_sheets_and_no_prose_chunks(
        self, conn: Connection, tenant_id: str, connection_id: str, xlsx_bytes: bytes
    ) -> None:
        result = _ingest(conn, tenant_id, connection_id, xlsx_bytes, "Q3 Budget.xlsx")
        assert result.sheets == EXPECTED_BUDGET_SHEETS
        assert result.chunks == 0
        # Indexed, not skipped: the sheet is real content awaiting summarisation.
        assert result.indexed

    def test_a_scanned_pdf_is_held_for_ocr_not_discarded(
        self, conn: Connection, tenant_id: str, connection_id: str, pdf_scanned: bytes
    ) -> None:
        result = _ingest(conn, tenant_id, connection_id, pdf_scanned, "Scan.pdf")
        assert result.ocr_pages == EXPECTED_SCANNED_PAGES
        assert result.status == "pending"
        assert result.status != "skipped"

    def test_an_unsupported_format_is_skipped_not_failed(
        self, conn: Connection, tenant_id: str, connection_id: str
    ) -> None:
        # 'failed' would be retried every sync forever; the format will not change.
        result = _ingest(conn, tenant_id, connection_id, b"PK\x03\x04junk", "archive.zip")
        assert result.status == "skipped"
        assert result.chunks == 0


class TestReingestion:
    """Re-syncing the same file must not duplicate or strand anything."""

    def test_reingesting_replaces_chunks_rather_than_appending(
        self, conn: Connection, tenant_id: str, connection_id: str, pdf_with_text: bytes
    ) -> None:
        remote = _remote("Acme Contract.pdf")
        content = FetchedContent(data=pdf_with_text, filename="Acme Contract.pdf", mime="")
        scope = Scope(tenant_id=tenant_id, connection_id=connection_id, source=SOURCE)
        args = {"scope": scope, "remote": remote}

        first = ingest_document(conn, content=content, **args)
        second = ingest_document(conn, content=content, **args)

        assert first.document_id == second.document_id
        assert second.chunks == first.chunks
        assert repo.count_chunks(conn, tenant_id=tenant_id, document_id=first.document_id) == (
            first.chunks
        )

    def test_deleting_a_document_cascades_to_its_chunks(
        self, conn: Connection, tenant_id: str, connection_id: str, pdf_with_text: bytes
    ) -> None:
        remote = _remote("Acme Contract.pdf")
        result = ingest_document(
            conn,
            scope=Scope(tenant_id=tenant_id, connection_id=connection_id, source=SOURCE),
            remote=remote,
            content=FetchedContent(data=pdf_with_text, filename="a.pdf", mime=""),
        )
        assert repo.count_chunks(conn, tenant_id=tenant_id, document_id=result.document_id) > 0

        removed = repo.delete_document(
            conn, tenant_id=tenant_id, source=SOURCE, external_id=remote.external_id
        )
        assert removed
        assert repo.count_chunks(conn, tenant_id=tenant_id, document_id=result.document_id) == 0


class TestTenantIsolation:
    """The invariant the whole schema is built around."""

    def test_chunks_are_not_visible_to_another_tenant(
        self, conn: Connection, tenant_id: str, connection_id: str, pdf_with_text: bytes
    ) -> None:
        result = _ingest(conn, tenant_id, connection_id, pdf_with_text, "Acme Contract.pdf")
        other = str(uuid.uuid4())
        assert repo.count_chunks(conn, tenant_id=other, document_id=result.document_id) == 0

    def test_deleting_under_the_wrong_tenant_is_a_no_op(
        self, conn: Connection, tenant_id: str, connection_id: str, pdf_with_text: bytes
    ) -> None:
        remote = _remote("Acme Contract.pdf")
        ingest_document(
            conn,
            scope=Scope(tenant_id=tenant_id, connection_id=connection_id, source=SOURCE),
            remote=remote,
            content=FetchedContent(data=pdf_with_text, filename="a.pdf", mime=""),
        )
        assert not repo.delete_document(
            conn, tenant_id=str(uuid.uuid4()), source=SOURCE, external_id=remote.external_id
        )


class TestCursorPersistence:
    """Incremental sync depends on the cursor surviving."""

    def test_cursor_round_trips(self, conn: Connection, connection_id: str) -> None:
        assert repo.get_cursor(conn, connection_id=connection_id) is None
        repo.save_cursor(conn, connection_id=connection_id, cursor="TOKEN-42")
        assert repo.get_cursor(conn, connection_id=connection_id) == "TOKEN-42"


class TestExtractionCache:
    """Keyed by content so OCR is never paid for twice."""

    def test_cache_round_trips(self, conn: Connection) -> None:
        digest = uuid.uuid4().hex
        assert repo.get_cached_extraction(conn, digest) is None
        repo.put_cached_extraction(
            conn, content_hash=digest, extractor="ocr", payload={"pages": ["one"]}
        )
        assert repo.get_cached_extraction(conn, digest) == {"pages": ["one"]}


class TestCorruptFiles:
    """A malformed file must not take the batch down with it.

    pymupdf, python-docx, python-pptx and openpyxl raise at least six unrelated
    exception types on malformed input. Enumerating them would regress the
    moment a dependency adds a seventh, so the pipeline treats any parser
    failure as this document's failure.
    """

    @pytest.mark.parametrize(("name", "data"), CORRUPT_FILES)
    def test_a_corrupt_file_is_recorded_failed_not_raised(
        self, conn: Connection, tenant_id: str, connection_id: str, name: str, data: bytes
    ) -> None:
        result = _ingest(conn, tenant_id, connection_id, data, name)
        assert result.status == "failed"
        assert result.reason

    def test_the_failure_is_persisted_for_inspection(
        self, conn: Connection, tenant_id: str, connection_id: str
    ) -> None:
        # The row must survive: an exception escaping would roll back the
        # transaction and leave no record that the file was ever seen.
        result = _ingest(conn, tenant_id, connection_id, b"", "empty.pdf")
        row = conn.execute(
            text("SELECT status, error FROM documents WHERE id = :d"),
            {"d": result.document_id},
        ).one()
        assert row.status == "failed"
        assert row.error

    def test_corrupt_is_failed_not_skipped(
        self, conn: Connection, tenant_id: str, connection_id: str
    ) -> None:
        # 'skipped' means never retry. A corrupt download is worth retrying;
        # an unsupported format is not.
        corrupt = _ingest(conn, tenant_id, connection_id, b"", "empty.pdf")
        unsupported = _ingest(conn, tenant_id, connection_id, b"PK\x03\x04junk", "a.zip")
        assert corrupt.status == "failed"
        assert unsupported.status == "skipped"

    def test_a_batch_survives_a_corrupt_member(
        self, conn: Connection, tenant_id: str, connection_id: str, pdf_with_text: bytes
    ) -> None:
        batch = [("bad.pdf", b""), ("good.pdf", pdf_with_text)]
        results = [_ingest(conn, tenant_id, connection_id, d, n) for n, d in batch]
        assert results[0].status == "failed"
        assert results[1].indexed  # the file after the corrupt one still indexed


class TestUnchangedContent:
    """Re-ingesting identical bytes must not redo extraction or embedding."""

    def test_unchanged_content_is_reported_and_keeps_its_chunks(
        self, conn: Connection, tenant_id: str, connection_id: str, pdf_with_text: bytes
    ) -> None:
        scope = Scope(tenant_id=tenant_id, connection_id=connection_id, source=SOURCE)
        remote = _remote("Acme Contract.pdf")
        content = FetchedContent(data=pdf_with_text, filename="Acme Contract.pdf", mime="")

        first = ingest_document(conn, scope=scope, remote=remote, content=content)
        second = ingest_document(conn, scope=scope, remote=remote, content=content)

        assert not first.unchanged
        assert second.unchanged
        assert second.chunks == first.chunks
        assert second.document_id == first.document_id

    def test_the_second_pass_does_no_embedding_work(
        self,
        conn: Connection,
        tenant_id: str,
        connection_id: str,
        pdf_with_text: bytes,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        scope = Scope(tenant_id=tenant_id, connection_id=connection_id, source=SOURCE)
        remote = _remote("Acme Contract.pdf")
        content = FetchedContent(data=pdf_with_text, filename="Acme Contract.pdf", mime="")
        ingest_document(conn, scope=scope, remote=remote, content=content)

        def _fail(_: object) -> list[list[float]]:
            msg = "embedding must not run for unchanged content"
            raise AssertionError(msg)

        monkeypatch.setattr("go2.jobs.ingest.embed_documents", _fail)
        assert ingest_document(conn, scope=scope, remote=remote, content=content).unchanged

    def test_changed_content_is_reprocessed(
        self,
        conn: Connection,
        tenant_id: str,
        connection_id: str,
        pdf_with_text: bytes,
        pdf_mixed: bytes,
    ) -> None:
        scope = Scope(tenant_id=tenant_id, connection_id=connection_id, source=SOURCE)
        remote = _remote("Acme Contract.pdf")

        ingest_document(
            conn,
            scope=scope,
            remote=remote,
            content=FetchedContent(data=pdf_with_text, filename="a.pdf", mime=""),
        )
        edited = ingest_document(
            conn,
            scope=scope,
            remote=remote,
            content=FetchedContent(data=pdf_mixed, filename="a.pdf", mime=""),
        )
        assert not edited.unchanged

    def test_a_renamed_file_updates_metadata_without_reprocessing(
        self, conn: Connection, tenant_id: str, connection_id: str, pdf_with_text: bytes
    ) -> None:
        scope = Scope(tenant_id=tenant_id, connection_id=connection_id, source=SOURCE)
        external_id = f"ext-{uuid.uuid4()}"
        content = FetchedContent(data=pdf_with_text, filename="a.pdf", mime="")

        ingest_document(
            conn,
            scope=scope,
            remote=RemoteFile(external_id=external_id, title="Old Name.pdf"),
            content=content,
        )
        renamed = ingest_document(
            conn,
            scope=scope,
            remote=RemoteFile(external_id=external_id, title="New Name.pdf"),
            content=content,
        )

        assert renamed.unchanged
        title = conn.execute(
            text("SELECT title FROM documents WHERE id = :d"), {"d": renamed.document_id}
        ).scalar_one()
        assert title == "New Name.pdf"

    def test_a_failed_document_is_retried_despite_the_same_hash(
        self, conn: Connection, tenant_id: str, connection_id: str
    ) -> None:
        # 'failed' is not settled: a transient parser error deserves another go.
        scope = Scope(tenant_id=tenant_id, connection_id=connection_id, source=SOURCE)
        remote = _remote("empty.pdf")
        content = FetchedContent(data=b"", filename="empty.pdf", mime="")

        first = ingest_document(conn, scope=scope, remote=remote, content=content)
        second = ingest_document(conn, scope=scope, remote=remote, content=content)
        assert first.status == "failed"
        assert not second.unchanged


class TestExtractionCacheReuse:
    """Identical bytes under a different identity replay the cached parse."""

    def test_the_same_content_is_parsed_once_across_documents(
        self,
        conn: Connection,
        tenant_id: str,
        connection_id: str,
        pdf_with_text: bytes,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The same file copied into two folders arrives as two documents. OCR
        # is the expensive stage, so the second must not re-parse.
        _ingest(conn, tenant_id, connection_id, pdf_with_text, "Copy A.pdf")

        def _fail(*_: object, **__: object) -> object:
            msg = "extraction must not rerun for content already cached"
            raise AssertionError(msg)

        monkeypatch.setattr("go2.jobs.ingest.extract", _fail)
        duplicate = _ingest(conn, tenant_id, connection_id, pdf_with_text, "Copy B.pdf")
        assert duplicate.indexed
        assert duplicate.chunks > 0

    def test_the_cache_entry_is_written(
        self, conn: Connection, tenant_id: str, connection_id: str, docx_bytes: bytes
    ) -> None:
        _ingest(conn, tenant_id, connection_id, docx_bytes, "Terms.docx")
        assert repo.get_cached_extraction(conn, content_hash(docx_bytes)) is not None
