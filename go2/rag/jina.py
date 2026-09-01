# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Jina AI embedding and reranking over HTTP.

The alternative to running these models on-device. Both stages are transformer
inference, which on a laptop CPU costs ~1 ms per character to embed and
saturates every core; moving them to an API turns that into a network round
trip and leaves the machine idle.

The trade is explicit and belongs in the open: document text and every query
leave the machine. That breaks the "retrieval stays local" invariant, so it is
opt-in through configuration rather than the default.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Any

import httpx

from go2.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

EMBEDDINGS_URL = "https://api.jina.ai/v1/embeddings"
RERANK_URL = "https://api.jina.ai/v1/rerank"

# Batches are built to a token budget rather than a fixed count. Chunk sizes
# vary by an order of magnitude, so "64 items" can be 5k tokens or 50k -- and
# the API bills and rate-limits by token, not by item.
DEFAULT_BATCH = 64
# Rough characters-per-token for mixed Latin/Arabic text. Deliberately
# conservative: overestimating tokens costs a little throughput, while
# underestimating them trips the rate limit and fails the whole ingest.
CHARS_PER_TOKEN = 3.0

_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 60.0


def estimate_tokens(text: str) -> int:
    """Approximate the token count the API will bill for this text."""
    return max(1, int(len(text) / CHARS_PER_TOKEN))


class _TokenBudget:
    """Keeps requests inside the account's tokens-per-minute allowance.

    A sliding window rather than a fixed one: the limit is enforced per rolling
    minute, so resetting a counter every 60 seconds would still burst over the
    boundary and be rejected.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._spent: list[tuple[float, int]] = []

    def acquire(self, tokens: int) -> None:
        """Block until ``tokens`` fit within the rolling allowance."""
        limit = get_settings().jina_tokens_per_minute
        while True:
            with self._lock:
                now = time.monotonic()
                self._spent = [(t, n) for t, n in self._spent if now - t < _WINDOW_SECONDS]
                used = sum(n for _, n in self._spent)
                if used + tokens <= limit or not self._spent:
                    self._spent.append((now, tokens))
                    return
                oldest = min(t for t, _ in self._spent)
                wait = _WINDOW_SECONDS - (now - oldest) + 0.5
            logger.info("rate limit: waiting %.0fs for token budget", wait)
            time.sleep(wait)


_budget = _TokenBudget()


def _batches(texts: Sequence[str]) -> list[list[str]]:
    """Split texts into batches that fit the per-request token budget."""
    limit = max(1, get_settings().jina_tokens_per_minute // 2)
    batches: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0

    for text in texts:
        tokens = estimate_tokens(text)
        too_many = len(current) >= DEFAULT_BATCH
        too_big = current and current_tokens + tokens > limit
        if too_many or too_big:
            batches.append(current)
            current, current_tokens = [], 0
        current.append(text)
        current_tokens += tokens

    if current:
        batches.append(current)
    return batches


class JinaError(RuntimeError):
    """Raised when the Jina API cannot be used."""


def _headers() -> dict[str, str]:
    key = get_settings().jina_api_key.get_secret_value()
    if not key:
        msg = (
            "GO2_JINA_API_KEY is not set. Get a free key at https://jina.ai "
            "or set GO2_EMBEDDING_PROVIDER=local to run on-device."
        )
        raise JinaError(msg)
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _post(url: str, payload: dict[str, Any], client: httpx.Client | None = None) -> dict[str, Any]:
    """POST to Jina and return the decoded body.

    Args:
        url: Endpoint.
        payload: JSON body.
        client: Optional client, so tests can supply a transport.

    Returns:
        The parsed response.

    Raises:
        JinaError: On any non-success response, with the API's own message
            where it gives one -- a bare status code is useless when the real
            cause is an exhausted token balance.
    """
    owns = client is None
    http = client or httpx.Client(timeout=_TIMEOUT)
    try:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = http.post(url, json=payload, headers=_headers())
            except httpx.HTTPError as exc:
                msg = f"could not reach the Jina API: {exc}"
                raise JinaError(msg) from exc

            if response.status_code == httpx.codes.OK:
                return dict(response.json())

            # 429 means the estimate was optimistic, not that the request is
            # wrong. Honour Retry-After when the API sends one; otherwise back
            # off geometrically rather than hammering a limit already tripped.
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS and attempt < _MAX_ATTEMPTS:
                delay = float(response.headers.get("retry-after") or 0) or min(
                    _WINDOW_SECONDS, 2.0**attempt
                )
                logger.info("rate limited, retrying in %.0fs (attempt %d)", delay, attempt)
                time.sleep(delay)
                continue

            msg = f"Jina API returned {response.status_code}: {response.text[:300]}"
            raise JinaError(msg)

        msg = f"Jina API still rate limiting after {_MAX_ATTEMPTS} attempts"
        raise JinaError(msg)
    finally:
        if owns:
            http.close()


def embed(
    texts: Sequence[str], *, task: str, client: httpx.Client | None = None
) -> list[list[float]]:
    """Embed texts through the Jina API.

    Args:
        texts: Texts to embed.
        task: ``retrieval.passage`` for documents, ``retrieval.query`` for
            questions. The asymmetry matters as much here as it does locally:
            the model places queries and passages in a shared space only when
            told which is which.
        client: Optional HTTP client for tests.

    Returns:
        One vector per input, in input order.

    Raises:
        JinaError: If the response does not carry one embedding per input.
    """
    if not texts:
        return []

    settings = get_settings()
    vectors: list[list[float]] = []

    for batch in _batches(texts):
        _budget.acquire(sum(estimate_tokens(t) for t in batch))
        body = _post(
            EMBEDDINGS_URL,
            {
                "model": settings.jina_embedding_model,
                "task": task,
                "normalized": True,
                "embedding_type": "float",
                "input": batch,
            },
            client=client,
        )
        data = body.get("data", [])
        if len(data) != len(batch):
            msg = f"Jina returned {len(data)} embeddings for {len(batch)} inputs"
            raise JinaError(msg)
        # The API does not promise ordering, but it does return an index.
        vectors.extend(
            [float(v) for v in item["embedding"]]
            for item in sorted(data, key=lambda d: int(d.get("index", 0)))
        )

    return vectors


def rerank(
    query: str, passages: Sequence[str], *, limit: int, client: httpx.Client | None = None
) -> list[tuple[int, float]]:
    """Rank passages against a query through the Jina API.

    Args:
        query: The user's question.
        passages: Candidate texts.
        limit: How many results to keep.
        client: Optional HTTP client for tests.

    Returns:
        ``(original_index, score)`` pairs, best first.
    """
    if not passages:
        return []

    body = _post(
        RERANK_URL,
        {
            "model": get_settings().jina_rerank_model,
            "query": query,
            "documents": list(passages),
            "top_n": limit,
            "return_documents": False,
        },
        client=client,
    )
    results = body.get("results", [])
    return [(int(r["index"]), float(r["relevance_score"])) for r in results][:limit]
