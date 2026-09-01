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
import re
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
            settings = get_settings()
            settings.model_cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info("loading reranker %s", settings.reranker_model)
            _model = TextCrossEncoder(
                model_name=settings.reranker_model,
                cache_dir=str(settings.model_cache_dir),
                threads=settings.inference_threads,
            )
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


# Words shorter than this carry too little signal to steer window selection
# ("is", "the") and appear everywhere, so they are ignored when locating the
# relevant part of a passage.
_MIN_TERM_CHARS = 3

_WORD = re.compile(r"\w+", re.UNICODE)


def select_window(text: str, query: str, budget: int) -> str:
    """Return the ``budget``-character span of ``text`` most relevant to the query.

    Reranking has to be given less text than a full chunk to stay fast, but
    taking the opening blindly loses any answer that sits later in the chunk.
    Measured: two candidates sharing an 810-character preamble scored
    *identically* under head truncation -- a 3.7 gap collapsed to 0.0 -- so the
    cross-encoder could not tell them apart at all.

    Choosing the window by query-term overlap keeps the same latency budget
    while pointing it at the part of the passage that might actually answer the
    question. Selection is lexical on purpose: it costs microseconds, and the
    cross-encoder still does the semantic judgement on whatever is chosen.

    Args:
        text: The full passage.
        query: The user's question.
        budget: Maximum characters to return.

    Returns:
        The best-scoring window, or the opening when nothing matches.
    """
    if len(text) <= budget:
        return text

    terms = {t for t in _WORD.findall(query.lower()) if len(t) >= _MIN_TERM_CHARS}
    if not terms:
        return text[:budget]

    step = max(budget // 2, 1)
    starts = list(range(0, len(text) - budget + 1, step))
    if starts[-1] != len(text) - budget:
        starts.append(len(text) - budget)  # always consider the tail

    best_start, best_key = 0, (-1, -1)
    for start in starts:
        window = text[start : start + budget].lower()
        distinct = sum(1 for t in terms if t in window)
        total = sum(window.count(t) for t in terms)
        # Distinct terms first: a window covering three query words beats one
        # repeating a single word many times. Earlier windows win ties.
        if (distinct, total) > best_key:
            best_key, best_start = (distinct, total), start

    return text[best_start : best_start + budget]


def rerank_order(query: str, passages: Sequence[str], *, limit: int) -> list[tuple[int, float]]:
    """Rank passages and return the best ones.

    Each passage is reduced to the window most relevant to the query before
    scoring. Cross-encoder cost is linear in passage length -- roughly 0.2 ms
    per character -- so the budget is what keeps search interactive; selecting
    the window by query overlap rather than taking the opening is what stops
    that budget hiding the answer. The reduction affects only the ordering;
    callers still hold the full text.

    Args:
        query: The user's question.
        passages: Candidate passage texts.
        limit: How many to keep.

    Returns:
        ``(original_index, score)`` pairs, best first, at most ``limit`` long.
    """
    settings = get_settings()
    windows = [select_window(p, query, settings.rerank_max_chars) for p in passages]

    if settings.rerank_provider == "jina":
        from go2.rag import jina  # noqa: PLC0415 -- optional path; keep httpx off the local import.

        return jina.rerank(query, windows, limit=limit)

    scores = rerank(query, windows)
    ranked = sorted(enumerate(scores), key=lambda pair: pair[1], reverse=True)
    return ranked[:limit]
