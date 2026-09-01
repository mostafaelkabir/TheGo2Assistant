# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""The single ingestion pipeline.

Every source -- upload, Google Drive, OneDrive -- passes through here. There is
no per-connector ingestion path, which is what keeps behaviour identical
regardless of where a file came from.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from go2.config import get_settings
from go2.extraction.base import UnsupportedFormatError
from go2.extraction.registry import content_hash, extract
from go2.rag.chunking import chunk_blocks
from go2.rag.embedding import embed_documents
from go2.storage import repository as repo

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from go2.connectors.base import FetchedContent, RemoteFile
    from go2.scope import Scope

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IngestResult:
    """What happened to one document."""

    document_id: str
    status: repo.DocStatus
    chunks: int = 0
    sheets: int = 0
    ocr_pages: int = 0
    reason: str | None = None

    @property
    def indexed(self) -> bool:
        """Whether the document is now searchable."""
        return self.status == "indexed"


def ingest_document(
    conn: Connection,
    *,
    scope: Scope,
    remote: RemoteFile,
    content: FetchedContent,
) -> IngestResult:
    """Extract, chunk, embed, and store one document.

    A file that cannot be parsed is recorded as ``skipped`` rather than
    ``failed``: an unsupported format is a fact about the file, not an error to
    retry, and retrying it every sync would be pure waste.

    Args:
        conn: An open transaction.
        scope: Owning tenant, connection, and source.
        remote: Provider metadata for the file.
        content: The fetched bytes and the filename to dispatch on.

    Returns:
        The outcome, including counts for chunks, sheets, and pages needing OCR.
    """
    digest = content_hash(content.data)
    document_id = repo.upsert_document(
        conn,
        scope=scope,
        remote=remote,
        content_hash=digest,
        status="extracting",
    )

    try:
        extracted = extract(content.data, content.filename, content.mime)
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
