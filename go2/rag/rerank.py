# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Local cross-encoder reranking.

Reranking is the single biggest quality lever after hybrid search: the fused
candidate list is recall-oriented and often puts the right passage at rank 7
rather than rank 1. A cross-encoder reads the query and passage together, which
a bi-encoder embedding never does.

The architecture plan named Qwen3-Reranker, but it is not usable here: it is a
causal LM that scores yes/no token logits rather than a standard cross-encoder,
so fastembed cannot serve it even as a custom model. jina-reranker-v2 is the
multilingual cross-encoder fastembed does support, and it separates relevant
from irrelevant passages cleanly for both English and Arabic queries.

Runs locally, so reranking stays free and no document text leaves the machine.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from fastembed.rerank.cross_encoder import TextCrossEncoder

from go2.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_model: TextCrossEncoder | None = None


def get_reranker() -> TextCrossEncoder:
    """Return the process-wide reranker, loading it on first use."""
    global _model  # noqa: PLW0603 -- one model per process; loading twice doubles memory.
    with _lock:
        if _model is None:
            name = get_settings().reranker_model
            logger.info("loading reranker %s", name)
            _model = TextCrossEncoder(model_name=name)
        return _model


def rerank(query: str, passages: Sequence[str]) -> list[float]:
    """Score each passage against the query.

    Args:
        query: The user's question.
        passages: Candidate passage texts.

    Returns:
        One score per passage, in input order. Higher is more relevant. Scores
        are unbounded logits, comparable only within a single call.
    """
    if not passages:
        return []
    return list(get_reranker().rerank(query, list(passages)))


def rerank_order(query: str, passages: Sequence[str], *, limit: int) -> list[tuple[int, float]]:
    """Rank passages and return the best ones.

    Passages are truncated before scoring. Cross-encoder cost is linear in
    passage length -- measured at roughly 0.2 ms per character -- and a
    relevance judgement rarely needs more than the opening of a passage. The
    truncation affects only the ordering; callers still hold the full text.

    Args:
        query: The user's question.
        passages: Candidate passage texts.
        limit: How many to keep.

    Returns:
        ``(original_index, score)`` pairs, best first, at most ``limit`` long.
    """
    budget = get_settings().rerank_max_chars
    scores = rerank(query, [p[:budget] for p in passages])
    ranked = sorted(enumerate(scores), key=lambda pair: pair[1], reverse=True)
    return ranked[:limit]
