# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Embedding tests.

These load the real Qwen3 ONNX model rather than a stub. A stub would verify
only the plumbing, and the things most likely to break here -- pooling
configuration, the query instruction prefix, vector geometry -- are exactly the
things a stub cannot catch.

Marked ``slow``: the first run downloads roughly 600 MB.
"""

from __future__ import annotations

import math

import pytest

from go2.config import get_settings
from go2.rag.embedding import QUERY_INSTRUCTION, embed_documents, embed_query

pytestmark = pytest.mark.slow

# Cosine similarity of unit vectors; 1.0 is identical, 0.0 is unrelated.
UNIT_TOLERANCE = 1e-5


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


class TestGeometry:
    """Shape and magnitude of what we store."""

    def test_dimension_matches_the_configured_schema(self) -> None:
        # A mismatch here fails at INSERT against vector(1024), not at read time.
        vector = embed_query("payment terms")
        assert len(vector) == get_settings().embedding_dim

    def test_vectors_are_unit_length(self) -> None:
        vector = embed_query("renewal date")
        assert math.isclose(math.sqrt(sum(c * c for c in vector)), 1.0, abs_tol=UNIT_TOLERANCE)

    def test_documents_are_embedded_in_order(self) -> None:
        texts = ["first passage about salaries", "second passage about cloud spend"]
        vectors = embed_documents(texts)
        assert len(vectors) == len(texts)
        assert _cosine(vectors[0], embed_documents([texts[0]])[0]) > 0.99

    def test_no_texts_means_no_model_call(self) -> None:
        assert embed_documents([]) == []


class TestRetrievalBehaviour:
    """The properties retrieval actually depends on."""

    def test_a_query_is_closer_to_a_relevant_passage_than_an_irrelevant_one(self) -> None:
        relevant, irrelevant = embed_documents(
            [
                "Invoices are due net 30 days from the invoice date.",
                "The office kitchen is restocked every Tuesday morning.",
            ]
        )
        query = embed_query("When do I have to pay an invoice?")
        assert _cosine(query, relevant) > _cosine(query, irrelevant)

    def test_queries_and_documents_are_embedded_asymmetrically(self) -> None:
        # The instruction prefix is what puts queries in the same space as
        # passages for this model. If it stopped being applied, this is the
        # only test that would notice.
        text = "What are the payment terms?"
        assert _cosine(embed_query(text), embed_documents([text])[0]) < 1.0 - UNIT_TOLERANCE

    def test_arabic_and_english_land_in_a_shared_space(self) -> None:
        # The corpus is mixed, so an Arabic question must retrieve an English
        # passage. This is the reason for a multilingual model.
        english, unrelated = embed_documents(
            [
                "The renewal fee is 4,500 USD payable annually.",
                "Parking permits are issued by the facilities team.",
            ]
        )
        arabic_query = embed_query("كم تبلغ رسوم التجديد؟")
        assert _cosine(arabic_query, english) > _cosine(arabic_query, unrelated)


def test_query_instruction_is_a_prefix_not_a_suffix() -> None:
    """Qwen3 expects the instruction ahead of the query text."""
    assert QUERY_INSTRUCTION.rstrip().endswith("Query:")
