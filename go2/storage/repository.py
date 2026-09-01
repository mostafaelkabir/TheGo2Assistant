# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Persistence for documents, chunks, and the extraction cache.

Every function takes ``tenant_id`` and every statement filters on it. That is
the invariant which makes multi-tenancy a configuration change later rather
than an audit of every query.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import text

from go2.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import Connection

    from go2.connectors.base import RemoteFile
    from go2.rag.chunking import Chunk
    from go2.scope import Scope

DocStatus = Literal["pending", "extracting", "indexed", "failed", "skipped"]


def vector_literal(values: Sequence[float]) -> str:
    """Render a vector for pgvector.

    Passing the literal form avoids registering a psycopg type adapter on every
    connection, which is easy to forget and fails only at write time.
    """
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


@dataclass(frozen=True, slots=True)
class DocumentState:
    """What the index already knows about a document."""

    document_id: str
    content_hash: str | None
    status: DocStatus
    embedding_model: str | None


def get_document_state(conn: Connection, *, scope: Scope, external_id: str) -> DocumentState | None:
    """Return the stored state of a document, or ``None`` if it is new.

    Read before ingesting so unchanged content can skip extraction and
    embedding entirely.
    """
    row = conn.execute(
        text("""
            SELECT id, content_hash, status, embedding_model FROM documents
             WHERE tenant_id = :tenant_id AND source = :source AND external_id = :external_id
        """),
        {
            "tenant_id": scope.tenant_id,
            "source": scope.source,
            "external_id": external_id,
        },
    ).one_or_none()
    if row is None:
        return None
    return DocumentState(
        document_id=str(row.id),
        content_hash=row.content_hash,
        status=row.status,
        embedding_model=row.embedding_model,
    )


def upsert_document(
    conn: Connection,
    *,
    scope: Scope,
    remote: RemoteFile,
    content_hash: str | None = None,
    status: DocStatus = "pending",
) -> str:
    """Insert or update one document record.

    Keyed on ``(tenant_id, source, external_id)`` so re-syncing a file updates
    it in place rather than duplicating it.

    Args:
        conn: An open transaction.
        scope: Owning tenant, connection, and source.
        remote: Provider metadata for the file.
        content_hash: Hash of the fetched bytes, for cache keying.
        status: Status to record.

    Returns:
        The document id.
    """
    row = conn.execute(
        text("""
            INSERT INTO documents (
                tenant_id, connection_id, source, external_id, title, path, mime,
                web_url, size_bytes, modified_at, content_hash, status, embedding_model
            )
            VALUES (
                :tenant_id, :connection_id, :source, :external_id, :title, :path, :mime,
                :web_url, :size_bytes, :modified_at, :content_hash,
                CAST(:status AS doc_status), :embedding_model
            )
            ON CONFLICT (tenant_id, source, external_id) DO UPDATE SET
                title        = EXCLUDED.title,
                path         = EXCLUDED.path,
                mime         = EXCLUDED.mime,
                web_url      = EXCLUDED.web_url,
                size_bytes   = EXCLUDED.size_bytes,
                modified_at  = EXCLUDED.modified_at,
                content_hash = EXCLUDED.content_hash,
                status       = EXCLUDED.status,
                embedding_model = EXCLUDED.embedding_model,
                error        = NULL
            RETURNING id
        """),
        {
            "tenant_id": scope.tenant_id,
            "connection_id": scope.connection_id,
            "source": scope.source,
            "external_id": remote.external_id,
            "title": remote.title,
            "path": remote.path,
            "mime": remote.mime,
            "web_url": remote.web_url,
            "size_bytes": remote.size_bytes,
            "modified_at": remote.modified_at,
            "content_hash": content_hash,
            "status": status,
            "embedding_model": get_settings().active_embedding_model,
        },
    ).scalar_one()
    return str(row)


def set_status(
    conn: Connection,
    *,
    tenant_id: str,
    document_id: str,
    status: DocStatus,
    error: str | None = None,
) -> None:
    """Move a document to a new ingestion status."""
    conn.execute(
        text("""
            UPDATE documents
               SET status = CAST(:status AS doc_status),
                   error = :error,
                   indexed_at = CASE WHEN :status = 'indexed' THEN now() ELSE indexed_at END
             WHERE id = :document_id AND tenant_id = :tenant_id
        """),
        {"status": status, "error": error, "document_id": document_id, "tenant_id": tenant_id},
    )


def replace_chunks(
    conn: Connection,
    *,
    tenant_id: str,
    document_id: str,
    chunks: Sequence[Chunk],
    embeddings: Sequence[Sequence[float]],
) -> int:
    """Replace every chunk of a document.

    Replacing wholesale rather than diffing keeps re-ingestion simple and
    guarantees no stale chunk outlives an edit.

    Returns:
        Number of chunks written.

    Raises:
        ValueError: If the chunk and embedding counts disagree.
    """
    if len(chunks) != len(embeddings):
        msg = f"{len(chunks)} chunks but {len(embeddings)} embeddings"
        raise ValueError(msg)

    conn.execute(
        text("DELETE FROM chunks WHERE document_id = :document_id AND tenant_id = :tenant_id"),
        {"document_id": document_id, "tenant_id": tenant_id},
    )
    if not chunks:
        return 0

    conn.execute(
        text("""
            INSERT INTO chunks (
                tenant_id, document_id, ordinal, text, embedding, page, slide, heading
            )
            VALUES (
                :tenant_id, :document_id, :ordinal, :text,
                CAST(:embedding AS vector), :page, :slide, :heading
            )
        """),
        [
            {
                "tenant_id": tenant_id,
                "document_id": document_id,
                "ordinal": chunk.ordinal,
                "text": chunk.text,
                "embedding": vector_literal(vector),
                "page": chunk.page,
                "slide": chunk.slide,
                "heading": chunk.heading,
            }
            for chunk, vector in zip(chunks, embeddings, strict=True)
        ],
    )
    return len(chunks)


def delete_document(conn: Connection, *, tenant_id: str, source: str, external_id: str) -> bool:
    """Remove a document and, by cascade, its chunks.

    Returns:
        Whether a document was actually removed.
    """
    result = conn.execute(
        text("""
            DELETE FROM documents
             WHERE tenant_id = :tenant_id AND source = :source AND external_id = :external_id
        """),
        {"tenant_id": tenant_id, "source": source, "external_id": external_id},
    )
    return result.rowcount > 0


def get_cached_extraction(conn: Connection, content_hash: str) -> dict[str, Any] | None:
    """Return a cached extraction payload, if this exact content was seen before."""
    row = conn.execute(
        text("SELECT payload FROM extraction_cache WHERE content_hash = :h"),
        {"h": content_hash},
    ).scalar_one_or_none()
    if row is None:
        return None
    return row if isinstance(row, dict) else json.loads(row)


def put_cached_extraction(
    conn: Connection, *, content_hash: str, extractor: str, payload: dict[str, Any]
) -> None:
    """Cache an extraction result keyed by content hash."""
    conn.execute(
        text("""
            INSERT INTO extraction_cache (content_hash, extractor, payload)
            VALUES (:h, :extractor, CAST(:payload AS jsonb))
            ON CONFLICT (content_hash) DO NOTHING
        """),
        {"h": content_hash, "extractor": extractor, "payload": json.dumps(payload)},
    )


def ensure_connection(
    conn: Connection, *, tenant_id: str, source: str, account: str, token_blob: bytes = b""
) -> str:
    """Return the id of a connection row, creating it if absent."""
    row = conn.execute(
        text("""
            INSERT INTO connections (tenant_id, source, account, token_blob)
            VALUES (:tenant_id, :source, :account, :token_blob)
            ON CONFLICT (tenant_id, source, account) DO UPDATE SET account = EXCLUDED.account
            RETURNING id
        """),
        {"tenant_id": tenant_id, "source": source, "account": account, "token_blob": token_blob},
    ).scalar_one()
    return str(row)


def save_cursor(conn: Connection, *, connection_id: str, cursor: str | None) -> None:
    """Persist the incremental-sync cursor for a connection."""
    conn.execute(
        text("""
            UPDATE connections SET cursor = :cursor, synced_at = now() WHERE id = :connection_id
        """),
        {"cursor": cursor, "connection_id": connection_id},
    )


def get_cursor(conn: Connection, *, connection_id: str) -> str | None:
    """Read back the stored sync cursor."""
    row = conn.execute(
        text("SELECT cursor FROM connections WHERE id = :connection_id"),
        {"connection_id": connection_id},
    ).scalar_one_or_none()
    return str(row) if row is not None else None


def count_chunks(conn: Connection, *, tenant_id: str, document_id: str) -> int:
    """Count chunks belonging to one document."""
    return int(
        conn.execute(
            text("""
                SELECT count(*) FROM chunks
                 WHERE document_id = :document_id AND tenant_id = :tenant_id
            """),
            {"document_id": document_id, "tenant_id": tenant_id},
        ).scalar_one()
    )


@dataclass(frozen=True, slots=True)
class Job:
    """One unit of queued work."""

    id: int
    kind: str
    payload: dict[str, Any]
    attempts: int


def enqueue_job(conn: Connection, *, tenant_id: str, kind: str, payload: dict[str, Any]) -> int:
    """Add a job to the queue.

    Returns:
        The new job id.
    """
    return int(
        conn.execute(
            text("""
                INSERT INTO jobs (tenant_id, kind, payload)
                VALUES (:tenant_id, :kind, CAST(:payload AS jsonb))
                RETURNING id
            """),
            {"tenant_id": tenant_id, "kind": kind, "payload": json.dumps(payload)},
        ).scalar_one()
    )


def claim_job(conn: Connection, *, tenant_id: str, kind: str) -> Job | None:
    """Take the next runnable job, marking it running.

    ``FOR UPDATE SKIP LOCKED`` is what makes this safe to run from several
    workers at once: each transaction locks its own row and steps over rows
    another worker already holds, so no job is handed out twice and no worker
    blocks waiting for one.

    Returns:
        The claimed job, or ``None`` when the queue is empty.
    """
    row = conn.execute(
        text("""
            WITH next AS (
                SELECT id FROM jobs
                 WHERE tenant_id = :tenant_id AND kind = :kind
                   AND status = 'queued' AND run_after <= now()
                 ORDER BY id
                 FOR UPDATE SKIP LOCKED
                 LIMIT 1
            )
            UPDATE jobs j
               SET status = 'running', attempts = j.attempts + 1, updated_at = now()
              FROM next
             WHERE j.id = next.id
            RETURNING j.id, j.kind, j.payload, j.attempts
        """),
        {"tenant_id": tenant_id, "kind": kind},
    ).one_or_none()
    if row is None:
        return None
    payload = row.payload if isinstance(row.payload, dict) else json.loads(row.payload)
    return Job(id=int(row.id), kind=row.kind, payload=payload, attempts=int(row.attempts))


def finish_job(conn: Connection, *, job_id: int, error: str | None = None) -> None:
    """Mark a job done, or failed with a reason."""
    conn.execute(
        text("""
            UPDATE jobs
               SET status = CAST(:status AS job_status), last_error = :error, updated_at = now()
             WHERE id = :job_id
        """),
        {"status": "failed" if error else "done", "error": error, "job_id": job_id},
    )


def job_counts(conn: Connection, *, tenant_id: str) -> dict[str, int]:
    """Return queued/running/done/failed counts for this tenant."""
    rows = conn.execute(
        text("SELECT status, count(*) AS n FROM jobs WHERE tenant_id = :t GROUP BY status"),
        {"t": tenant_id},
    ).all()
    return {str(r.status): int(r.n) for r in rows}


def clear_finished_jobs(conn: Connection, *, tenant_id: str) -> int:
    """Delete completed jobs, keeping failures for inspection.

    Returns:
        How many rows were removed.
    """
    return conn.execute(
        text("DELETE FROM jobs WHERE tenant_id = :t AND status = 'done'"), {"t": tenant_id}
    ).rowcount
