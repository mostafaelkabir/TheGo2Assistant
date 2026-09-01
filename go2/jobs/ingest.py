# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""The single ingestion pipeline.

Every source -- upload, Google Drive, OneDrive -- passes through here. There is
no per-connector ingestion path, which is what keeps behaviour identical
regardless of where a file came from.

Work is avoided at two levels, both keyed on the content hash:

* If the document's stored hash already matches, extraction and embedding are
  skipped entirely and only metadata is refreshed.
* Otherwise the extraction cache is consulted, so identical bytes arriving
  under a different name or folder replay a previous parse instead of redoing
  it. That matters most for OCR, the only meaningful per-file cost.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from go2.config import get_settings
from go2.extraction.base import Extracted, UnsupportedFormatError
from go2.extraction.registry import content_hash, extract
from go2.rag.chunking import chunk_blocks
from go2.rag.embedding import embed_documents
from go2.storage import repository as repo

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from go2.connectors.base import FetchedContent, RemoteFile
    from go2.scope import Scope

logger = logging.getLogger(__name__)

# Statuses that represent a completed decision about this exact content.
# Anything else ('extracting' from an interrupted run, 'failed' from a
# transient parser error) is worth retrying even when the hash is unchanged.
_SETTLED: frozenset[str] = frozenset({"indexed", "skipped", "pending"})


@dataclass(frozen=True, slots=True)
class IngestResult:
    """What happened to one document."""

    document_id: str
    status: repo.DocStatus
    chunks: int = 0
    sheets: int = 0
    ocr_pages: int = 0
    reason: str | None = None
    # True when the content hash was unchanged and no work was redone.
    unchanged: bool = False

    @property
    def indexed(self) -> bool:
        """Whether the document is now searchable."""
        return self.status == "indexed"


def _extract_cached(conn: Connection, content: FetchedContent, digest: str) -> Extracted:
    """Extract, replaying a cached parse of identical bytes when one exists."""
    cached = repo.get_cached_extraction(conn, digest)
    if cached is not None:
        logger.debug("extraction cache hit for %s", digest[:12])
        return Extracted.from_payload(cached)

    extracted = extract(content.data, content.filename, content.mime)
    repo.put_cached_extraction(
        conn, content_hash=digest, extractor=content.filename, payload=extracted.to_payload()
    )
    return extracted


def ingest_document(
    conn: Connection,
    *,
    scope: Scope,
    remote: RemoteFile,
    content: FetchedContent,
) -> IngestResult:
    """Extract, chunk, embed, and store one document.

    Failure is recorded, never raised. A corrupt file must not abort the batch
    it arrived in, so any parser error is confined to its own document.

    The three terminal states mean different things and are deliberately not
    collapsed: ``skipped`` is a permanent fact about the file (an unsupported
    format will not become supported, so retrying it every sync is waste),
    ``failed`` is worth retrying, and ``pending`` means real content is waiting
    on the OCR stage.

    Args:
        conn: An open transaction.
        scope: Owning tenant, connection, and source.
        remote: Provider metadata for the file.
        content: The fetched bytes and the filename to dispatch on.

    Returns:
        The outcome, including counts for chunks, sheets, and pages needing OCR.
    """
    digest = content_hash(content.data)
    previous = repo.get_document_state(conn, scope=scope, external_id=remote.external_id)

    # Unchanged content: refresh metadata (a file may have been renamed or
    # moved) but do not re-extract or re-embed.
    if previous is not None and previous.content_hash == digest and previous.status in _SETTLED:
        repo.upsert_document(
            conn, scope=scope, remote=remote, content_hash=digest, status=previous.status
        )
        logger.debug("unchanged, skipping re-ingest: %s", remote.title)
        return IngestResult(
            document_id=previous.document_id,
            status=previous.status,
            chunks=repo.count_chunks(
                conn, tenant_id=scope.tenant_id, document_id=previous.document_id
            ),
            reason="unchanged",
            unchanged=True,
        )

    document_id = repo.upsert_document(
        conn, scope=scope, remote=remote, content_hash=digest, status="extracting"
    )

    try:
        extracted = _extract_cached(conn, content, digest)
    except UnsupportedFormatError as exc:
        logger.info("skipping %s: %s", remote.title, exc)
        repo.set_status(
            conn,
            tenant_id=scope.tenant_id,
            document_id=document_id,
            status="skipped",
            error=str(exc),
        )
        return IngestResult(document_id=document_id, status="skipped", reason=str(exc))
    except Exception as exc:  # noqa: BLE001 -- a per-document boundary must contain
        # arbitrary parser failures. pymupdf, python-docx, python-pptx and openpyxl
        # raise at least six unrelated exception types on malformed input
        # (FileDataError, EmptyFileError, BadZipFile, ...), and enumerating them
        # would silently regress the moment a dependency adds a seventh.
        reason = f"{type(exc).__name__}: {exc}"
        logger.warning("extraction failed for %s: %s", remote.title, reason)
        repo.set_status(
            conn,
            tenant_id=scope.tenant_id,
            document_id=document_id,
            status="failed",
            error=reason,
        )
        return IngestResult(document_id=document_id, status="failed", reason=reason)

    settings = get_settings()
    chunks = chunk_blocks(
        extracted.blocks,
        max_chars=settings.chunk_chars,
        overlap_chars=settings.chunk_overlap_chars,
    )

    embeddings = embed_documents([c.text for c in chunks])
    written = repo.replace_chunks(
        conn,
        tenant_id=scope.tenant_id,
        document_id=document_id,
        chunks=chunks,
        embeddings=embeddings,
    )

    # A scanned PDF has no chunks yet but is not empty -- OCR runs later and
    # will fill it in. Calling that 'skipped' would strand the document.
    if written == 0 and not extracted.sheets and not extracted.ocr_pages:
        repo.set_status(
            conn,
            tenant_id=scope.tenant_id,
            document_id=document_id,
            status="skipped",
            error="no extractable content",
        )
        return IngestResult(
            document_id=document_id, status="skipped", reason="no extractable content"
        )

    status: repo.DocStatus = "pending" if extracted.ocr_pages and written == 0 else "indexed"
    repo.set_status(conn, tenant_id=scope.tenant_id, document_id=document_id, status=status)

    return IngestResult(
        document_id=document_id,
        status=status,
        chunks=written,
        sheets=len(extracted.sheets),
        ocr_pages=len(extracted.ocr_pages),
    )
