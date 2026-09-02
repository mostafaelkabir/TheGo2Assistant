# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""The retrieval tools.

These are the agent's surface. They are plain typed functions so the same
implementations serve the MCP server today and an in-process agent loop later
-- exposing retrieval as tools rather than a single-shot RAG call is what lets
the model reformulate a bad query, page through a document, and combine
metadata filters with semantic search.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from go2.config import get_settings
from go2.observability import Trace
from go2.rag.retrieval import SearchFilters, SearchOptions, search
from go2.storage.db import connect, default_tenant_id

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy import Connection

MAX_SNIPPET_CHARS = 1200


def unsearchable_count(conn: Connection, tenant_id: str) -> int:
    """Documents indexed under a different embedding model than the active one.

    An empty result is ambiguous: nothing matched, or nothing *could* match
    because the configured provider does not own these vectors. Counting the
    mismatch lets callers tell the two apart.
    """
    return int(
        conn.execute(
            text("""
                SELECT count(*) FROM documents
                 WHERE tenant_id = :t AND embedding_model IS DISTINCT FROM :m
            """),
            {"t": tenant_id, "m": get_settings().active_embedding_model},
        ).scalar_one()
    )


@dataclass(frozen=True, slots=True)
class DocumentSummary:
    """One document as metadata, without its text."""

    document_id: str
    title: str
    source: str
    status: str
    path: str
    modified_at: datetime | None
    chunks: int
    web_url: str | None


def search_documents(
    query: str,
    *,
    limit: int = 8,
    source: str | None = None,
    title_contains: str | None = None,
) -> dict[str, Any]:
    """Find passages answering a question.

    Args:
        query: A natural-language question. Full sentences work better than
            keywords, because half the retrieval is semantic.
        limit: Maximum passages to return.
        source: Restrict to one connector, e.g. ``gdrive`` or ``upload``.
        title_contains: Restrict to documents whose title contains this text.

    Returns:
        A result carrying the passages *and* an explicit judgement about
        whether they constitute evidence. Retrieval always returns its best
        candidates, however poor; without that judgement the caller cannot
        distinguish "here is the answer" from "here is the least irrelevant
        paragraph I have", and the second is what ungrounded answers are made
        from.
    """
    tenant_id = default_tenant_id()
    settings = get_settings()
    trace = Trace(kind="search", label=query)
    started = time.perf_counter()
    with connect() as conn:
        hits = search(
            conn,
            tenant_id=tenant_id,
            query=query,
            filters=SearchFilters(source=source, title_contains=title_contains),
            options=SearchOptions(limit=limit, trace=trace),
        )
        stranded = unsearchable_count(conn, tenant_id) if not hits else 0

    threshold = settings.min_evidence_score
    best = hits[0].score if hits else None
    sufficient = best is not None and best >= threshold
    strong = [h for h in hits if h.score >= threshold]

    if sufficient:
        guidance = (
            "Answer using only these passages. Cite the `citation` of every passage "
            "you rely on. If they cover only part of the question, answer that part "
            "and say plainly what is not covered."
        )
    elif hits:
        guidance = (
            f"NOT ENOUGH EVIDENCE. The best passage scored {best:.2f}, below the "
            f"{threshold:.2f} floor, so these are the least irrelevant passages rather "
            "than an answer. Do not answer from them and do not answer from your own "
            "knowledge. Tell the user the documents do not cover this, and offer to "
            "rephrase or to check another source."
        )
    else:
        guidance = (
            "No passages matched. Tell the user nothing in the indexed documents "
            "covers this question."
        )
        if stranded:
            guidance += (
                f" Note: {stranded} documents are indexed under a different embedding "
                "model and are currently unsearchable."
            )

    trace.duration_ms = (time.perf_counter() - started) * 1000
    trace.outcome = "answered" if sufficient else "refused"
    trace.meta = {"threshold": threshold, "best_score": best, "returned": len(hits)}
    trace.save(tenant_id=tenant_id)

    return {
        "sufficient_evidence": sufficient,
        "best_score": round(best, 4) if best is not None else None,
        "evidence_threshold": threshold,
        "guidance": guidance,
        "passages": [
            {
                "document_id": hit.document_id,
                "title": hit.title,
                "location": hit.location,
                "citation": hit.citation(),
                "source": hit.source,
                "score": round(hit.score, 4),
                "meets_threshold": hit.score >= threshold,
                "text": hit.text[:MAX_SNIPPET_CHARS],
                "web_url": hit.web_url,
            }
            for hit in (strong if sufficient else hits)
        ],
    }


def fetch_document(
    document_id: str, *, page: int | None = None, max_chars: int = 12000
) -> dict[str, Any]:
    """Read a document's full text when snippets are not enough.

    Args:
        document_id: Id from a ``search_documents`` result.
        page: Restrict to a single page, if the document has pages.
        max_chars: Truncation budget for the returned text.

    Returns:
        The document's metadata and text, marked if truncated.
    """
    tenant_id = default_tenant_id()
    clause = "AND c.page = :page" if page is not None else ""
    with connect() as conn:
        meta = conn.execute(
            text("""
                SELECT id, title, source, status, path, mime, web_url, modified_at
                  FROM documents WHERE id = CAST(:d AS uuid) AND tenant_id = :t
            """),
            {"d": document_id, "t": tenant_id},
        ).one_or_none()
        if meta is None:
            return {"error": f"no document {document_id}"}

        rows = conn.execute(
            text(f"""
                SELECT c.text, c.page, c.slide, c.heading FROM chunks c
                 WHERE c.document_id = CAST(:d AS uuid) AND c.tenant_id = :t {clause}
                 ORDER BY c.ordinal
            """),  # noqa: S608 -- `clause` is a fixed string, never user input.
            {"d": document_id, "t": tenant_id, **({"page": page} if page is not None else {})},
        ).all()

    body = "\n\n".join(r.text for r in rows)
    return {
        "document_id": str(meta.id),
        "title": meta.title,
        "source": meta.source,
        "status": meta.status,
        "path": meta.path,
        "web_url": meta.web_url,
        "pages": sorted({r.page for r in rows if r.page is not None}),
        "text": body[:max_chars],
        "truncated": len(body) > max_chars,
    }


def list_documents(
    *,
    source: str | None = None,
    title_contains: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List indexed documents by metadata.

    Answers questions vector search cannot -- "which contracts do we have",
    "what came from Drive last week" -- because those are properties of the
    file, not of any passage inside it.

    Args:
        source: Restrict to one connector.
        title_contains: Restrict to titles containing this text.
        status: Restrict to an ingestion status, e.g. ``indexed`` or ``failed``.
        limit: Maximum documents to return.

    Returns:
        Document metadata, most recently modified first.
    """
    tenant_id = default_tenant_id()
    parts = ["d.tenant_id = :t"]
    params: dict[str, Any] = {"t": tenant_id, "limit": limit}
    if source:
        parts.append("d.source = :source")
        params["source"] = source
    if title_contains:
        parts.append("d.title ILIKE :title")
        params["title"] = f"%{title_contains}%"
    if status:
        parts.append("d.status = CAST(:status AS doc_status)")
        params["status"] = status

    where = " AND ".join(parts)
    with connect() as conn:
        rows = conn.execute(
            text(f"""
                SELECT d.id, d.title, d.source, d.status, d.path, d.web_url, d.modified_at,
                       (SELECT count(*) FROM chunks c WHERE c.document_id = d.id) AS chunks
                  FROM documents d WHERE {where}
                 ORDER BY d.modified_at DESC NULLS LAST, d.title LIMIT :limit
            """),  # noqa: S608 -- every fragment is a fixed string; values are bound.
            params,
        ).all()

    return [
        {
            "document_id": str(r.id),
            "title": r.title,
            "source": r.source,
            "status": r.status,
            "path": r.path,
            "modified_at": r.modified_at.isoformat() if r.modified_at else None,
            "chunks": r.chunks,
            "web_url": r.web_url,
        }
        for r in rows
    ]
