# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Jina provider tests.

Driven by an httpx MockTransport, so the request bodies and response handling
are pinned without a key or a network call. What matters here is the wire
contract: a wrong field name fails silently as an empty result rather than an
error, which is exactly the kind of bug that reaches production.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from go2.config import get_settings
from go2.rag import jina

if TYPE_CHECKING:
    from collections.abc import Iterator

DIM = 4
EXPECTED_TWO = 2


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give the settings a key through the real environment path.

    Clearing the cache rather than patching the model keeps the test on the
    same code path production uses to read configuration.
    """
    monkeypatch.setenv("GO2_JINA_API_KEY", "test-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _client(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestEmbed:
    """Request shape and ordering."""

    def test_sends_the_task_and_returns_vectors_in_order(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(request.content))
            # Deliberately out of order: the API documents an index, not order.
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 1, "embedding": [1.0] * DIM},
                        {"index": 0, "embedding": [0.0] * DIM},
                    ]
                },
            )

        vectors = jina.embed(["a", "b"], task="retrieval.passage", client=_client(handler))

        assert seen["task"] == "retrieval.passage"
        assert seen["input"] == ["a", "b"]
        assert seen["normalized"] is True
        assert vectors[0] == [0.0] * DIM  # reordered by index, not response order
        assert vectors[1] == [1.0] * DIM

    def test_queries_use_the_query_task(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(request.content))
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.5] * DIM}]})

        jina.embed(["q"], task="retrieval.query", client=_client(handler))
        # Query/passage asymmetry is what puts them in a shared space; losing
        # it degrades retrieval silently.
        assert seen["task"] == "retrieval.query"

    def test_no_texts_makes_no_request(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            pytest.fail("should not call the API for an empty batch")

        assert jina.embed([], task="retrieval.passage", client=_client(handler)) == []

    def test_a_short_response_is_an_error_not_silent_loss(self) -> None:
        # Returning fewer vectors than inputs would misalign every chunk with
        # the wrong text if it were allowed through.
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.0] * DIM}]})

        with pytest.raises(jina.JinaError, match="1 embeddings for 2"):
            jina.embed(["a", "b"], task="retrieval.passage", client=_client(handler))

    def test_batches_large_inputs(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            n = len(json.loads(request.content)["input"])
            return httpx.Response(
                200, json={"data": [{"index": i, "embedding": [0.0] * DIM} for i in range(n)]}
            )

        vectors = jina.embed(
            ["x"] * (jina.DEFAULT_BATCH + 5), task="retrieval.passage", client=_client(handler)
        )
        assert calls == EXPECTED_TWO
        assert len(vectors) == jina.DEFAULT_BATCH + 5


class TestRerank:
    """Ranking round trip."""

    def test_returns_index_score_pairs(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"index": 2, "relevance_score": 0.9},
                        {"index": 0, "relevance_score": 0.1},
                    ]
                },
            )

        assert jina.rerank("q", ["a", "b", "c"], limit=5, client=_client(handler)) == [
            (2, 0.9),
            (0, 0.1),
        ]

    def test_sends_the_query_and_documents(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(request.content))
            return httpx.Response(200, json={"results": []})

        jina.rerank("what is the fee?", ["a", "b"], limit=2, client=_client(handler))
        assert seen["query"] == "what is the fee?"
        assert seen["documents"] == ["a", "b"]
        assert seen["top_n"] == EXPECTED_TWO

    def test_no_passages_makes_no_request(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            pytest.fail("should not call the API with no candidates")

        assert jina.rerank("q", [], limit=5, client=_client(handler)) == []


class TestFailures:
    """Errors must say what to do about them."""

    def test_an_api_error_carries_the_response_body(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(402, text="insufficient token balance")

        with pytest.raises(jina.JinaError, match="insufficient token balance"):
            jina.embed(["a"], task="retrieval.passage", client=_client(handler))

    def test_a_network_failure_is_wrapped(self) -> None:
        message = "connection refused"

        def handler(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(message)

        with pytest.raises(jina.JinaError, match="could not reach"):
            jina.embed(["a"], task="retrieval.passage", client=_client(handler))


def test_a_missing_key_explains_both_ways_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """The error should name the env var and the local fallback."""
    monkeypatch.setenv("GO2_JINA_API_KEY", "")
    get_settings.cache_clear()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    with pytest.raises(jina.JinaError, match="GO2_JINA_API_KEY"):
        jina.embed(["a"], task="retrieval.passage", client=_client(handler))


class TestTokenBatching:
    """Batching is by token budget, because that is what the API limits."""

    def test_a_small_batch_stays_whole(self) -> None:
        assert jina._batches(["a", "b", "c"]) == [["a", "b", "c"]]  # noqa: SLF001

    def test_batches_split_on_the_item_cap(self) -> None:
        batches = jina._batches(["x"] * (jina.DEFAULT_BATCH + 1))  # noqa: SLF001
        assert len(batches) == EXPECTED_TWO
        assert len(batches[0]) == jina.DEFAULT_BATCH

    def test_batches_split_on_the_token_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Two chunks can exceed a token budget that a hundred short ones would
        # not, which is exactly why counting items is the wrong unit.
        monkeypatch.setenv("GO2_JINA_TOKENS_PER_MINUTE", "2000")
        get_settings.cache_clear()
        huge = "w" * 3000  # ~1000 tokens each, budget/2 = 1000
        assert len(jina._batches([huge, huge, huge])) > 1  # noqa: SLF001

    def test_token_estimate_is_conservative(self) -> None:
        # Underestimating trips the rate limit and fails the run; overestimating
        # only costs a little throughput.
        assert jina.estimate_tokens("a" * 300) >= 100
        assert jina.estimate_tokens("") == 1


class TestRateLimitRetry:
    """A 429 means slow down, not give up."""

    def test_retries_after_a_429_then_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(jina.time, "sleep", lambda _: None)
        calls = 0

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(429, text="rate limited", headers={"retry-after": "0"})
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.0] * DIM}]})

        vectors = jina.embed(["a"], task="retrieval.passage", client=_client(handler))
        assert calls == EXPECTED_TWO
        assert len(vectors) == 1

    def test_gives_up_with_a_clear_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(jina.time, "sleep", lambda _: None)

        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="rate limited")

        with pytest.raises(jina.JinaError, match="rate limit"):
            jina.embed(["a"], task="retrieval.passage", client=_client(handler))

    def test_a_non_429_error_is_not_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(jina.time, "sleep", lambda _: None)
        calls = 0

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(401, text="invalid key")

        with pytest.raises(jina.JinaError, match="invalid key"):
            jina.embed(["a"], task="retrieval.passage", client=_client(handler))
        assert calls == 1  # a bad key will not fix itself
