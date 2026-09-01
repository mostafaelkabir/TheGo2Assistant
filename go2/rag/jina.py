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
from typing import TYPE_CHECKING, Any

import httpx

from go2.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

EMBEDDINGS_URL = "https://api.jina.ai/v1/embeddings"
RERANK_URL = "https://api.jina.ai/v1/rerank"

# The free tier allows 100 requests/minute and 100k tokens/minute, so requests
# are batched rather than sent per chunk.
DEFAULT_BATCH = 64
_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


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
        response = http.post(url, json=payload, headers=_headers())
        if response.status_code != httpx.codes.OK:
            detail = response.text[:300]
            msg = f"Jina API returned {response.status_code}: {detail}"
            raise JinaError(msg)
        return dict(response.json())
    except httpx.HTTPError as exc:
        msg = f"could not reach the Jina API: {exc}"
        raise JinaError(msg) from exc
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

    for start in range(0, len(texts), DEFAULT_BATCH):
        batch = list(texts[start : start + DEFAULT_BATCH])
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
