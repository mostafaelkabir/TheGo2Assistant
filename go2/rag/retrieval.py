# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Hybrid retrieval: vector search, full-text search, fusion, then reranking.

Keyword search is not optional here. Exact identifiers -- invoice numbers,
client names, filenames -- are precisely what embeddings are worst at and
precisely what people search for. Vector search alone misses them; full-text
alone misses paraphrase and cross-language questions. Running both and fusing
the ranks costs one extra query and covers both failure modes.

Fusion is Reciprocal Rank Fusion, which combines by *rank* rather than score.
That matters because cosine distance and ts_rank_cd are not on comparable
scales, so any weighted sum of the two raw scores would be arbitrary.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, cast

from sqlalchemy import text

from go2.config import get_settings
from go2.rag.embedding import embed_query
from go2.storage.repository import vector_literal

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy import Connection

logger = logging.getLogger(__name__)

# Standard RRF damping. Large enough that the top few ranks of either retriever
# carry similar weight, so one retriever cannot dominate on rank alone.
RRF_K = 60


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """Metadata narrowing applied before ranking."""

    source: str | None = None
    title_contains: str | None = None
    modified_after: datetime | None = None
    modified_before: datetime | None = None

    def clauses(self) -> tuple[list[str], dict[str, Any]]:
        """Render SQL fragments and their bound parameters.

        Fragments are fixed strings and every value is bound, so a filter can
        never carry SQL into the query.
        """
        parts: list[str] = []
        params: dict[str, Any] = {}
        if self.source:
            parts.append("d.source = :f_source")
            params["f_source"] = self.source
        if self.title_contains:
            parts.append("d.title ILIKE :f_title")
            params["f_title"] = f"%{self.title_contains}%"
        if self.modified_after:
            parts.append("d.modified_at >= :f_after")
            params["f_after"] = self.modified_after
        if self.modified_before:
            parts.append("d.modified_at <= :f_before")
            params["f_before"] = self.modified_before
        return parts, params


class RetrievedRow(Protocol):
    """The row shape retrieval depends on.

    Stated as a protocol rather than ``sqlalchemy.Row`` because that is the
    real contract: fusion needs an identity, reranking needs the text, and
    citation needs the location. Anything supplying those works.
    """

    chunk_id: Any
    document_id: Any
    text: str
    page: int | None
    slide: int | None
    heading: str | None
    title: str
    source: str
    web_url: str | None


@dataclass(frozen=True, slots=True)
class SearchOptions:
    """Tuning for one search."""

    limit: int = 10
    # Retrieved from each retriever before fusion. Recall-oriented: the
    # reranker is what turns a wide candidate pool into a precise answer.
    candidates: int = 50
    rerank: bool = True


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One retrieved passage, with everything needed to cite it."""

    chunk_id: str
    document_id: str
    title: str
    source: str
    text: str
    score: float
    page: int | None = None
    slide: int | None = None
    heading: str | None = None
    web_url: str | None = None

    @property
    def location(self) -> str:
        """Human-readable position within the document."""
        if self.page is not None:
            return f"p.{self.page}"
        if self.slide is not None:
            return f"slide {self.slide}"
        if self.heading:
            return self.heading
        return ""

    def citation(self) -> str:
        """A compact source reference, e.g. ``Acme Contract.pdf p.2``."""
        location = self.location
        return f"{self.title} {location}".strip()


@dataclass
class _Candidate:
    row: RetrievedRow
    rrf: float = 0.0
    ranks: dict[str, int] = field(default_factory=dict)


_SELECT = """
    SELECT c.id AS chunk_id, c.document_id, c.text, c.page, c.slide, c.heading,
           d.title, d.source, d.web_url
      FROM chunks c JOIN documents d ON d.id = c.document_id
"""


def _where(filters: SearchFilters, extra: str = "") -> tuple[str, dict[str, Any]]:
    parts, params = filters.clauses()
    parts.insert(0, "c.tenant_id = :tenant_id")
    if extra:
        parts.append(extra)
    return " WHERE " + " AND ".join(parts), params


def _vector_candidates(
    conn: Connection, *, tenant_id: str, query: str, limit: int, filters: SearchFilters
) -> list[RetrievedRow]:
    where, params = _where(filters)
    sql = f"{_SELECT}{where} ORDER BY c.embedding <=> CAST(:qvec AS vector) LIMIT :limit"
    # SQLAlchemy's Row resolves columns through __getattr__, so it cannot be
    # statically checked against the protocol. The cast is sound because
    # _SELECT names exactly the columns RetrievedRow declares.
    return cast(
        "list[RetrievedRow]",
        list(
            conn.execute(
                text(sql),
                {
                    "tenant_id": tenant_id,
                    "qvec": vector_literal(embed_query(query)),
                    "limit": limit,
                    **params,
                },
            ).all()
        ),
    )


def _text_candidates(
    conn: Connection, *, tenant_id: str, query: str, limit: int, filters: SearchFilters
) -> list[RetrievedRow]:
    where, params = _where(filters, "c.tsv @@ plainto_tsquery('simple', :qtext)")
    sql = (
        f"{_SELECT}{where} "
        "ORDER BY ts_rank_cd(c.tsv, plainto_tsquery('simple', :qtext)) DESC LIMIT :limit"
    )
    return cast(
        "list[RetrievedRow]",
        list(
            conn.execute(
                text(sql), {"tenant_id": tenant_id, "qtext": query, "limit": limit, **params}
            ).all()
        ),
    )


def _fuse(ranked_lists: dict[str, list[RetrievedRow]]) -> list[_Candidate]:
    """Combine ranked lists by Reciprocal Rank Fusion."""
    merged: dict[str, _Candidate] = {}
    for name, rows in ranked_lists.items():
        for rank, row in enumerate(rows, start=1):
            key = str(row.chunk_id)
            candidate = merged.setdefault(key, _Candidate(row=row))
            candidate.rrf += 1.0 / (RRF_K + rank)
            candidate.ranks[name] = rank
    return sorted(merged.values(), key=lambda c: c.rrf, reverse=True)


def search(
    conn: Connection,
    *,
    tenant_id: str,
    query: str,
    filters: SearchFilters | None = None,
    options: SearchOptions | None = None,
) -> list[SearchHit]:
    """Search indexed documents.

    Args:
        conn: An open connection.
        tenant_id: Owning tenant; every query filters on it.
        query: The user's question.
        filters: Optional metadata narrowing.
        options: Tuning. Defaults are the ones the tools use.

    Returns:
        Hits ordered best first.
    """
    if not query.strip():
        return []

    active = filters or SearchFilters()
    opts = options or SearchOptions()
    fused = _fuse(
        {
            "vector": _vector_candidates(
                conn, tenant_id=tenant_id, query=query, limit=opts.candidates, filters=active
            ),
            "text": _text_candidates(
                conn, tenant_id=tenant_id, query=query, limit=opts.candidates, filters=active
            ),
        }
    )
    if not fused:
        return []

    if opts.rerank:
        from go2.rag.rerank import rerank_order  # noqa: PLC0415 -- defer the model import.

        pool = fused[: get_settings().rerank_candidates]
        ordered = rerank_order(query, [c.row.text for c in pool], limit=opts.limit)
        return [_hit(pool[i].row, score) for i, score in ordered]

    return [_hit(c.row, c.rrf) for c in fused[: opts.limit]]


def _hit(row: RetrievedRow, score: float) -> SearchHit:
    return SearchHit(
        chunk_id=str(row.chunk_id),
        document_id=str(row.document_id),
        title=row.title,
        source=row.source,
        text=row.text,
        score=float(score),
        page=row.page,
        slide=row.slide,
        heading=row.heading,
        web_url=row.web_url,
    )
