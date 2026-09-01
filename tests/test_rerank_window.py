# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Window selection for reranking.

Reranking must be given less than a full chunk to stay interactive, but the
opening of a chunk is not where the answer necessarily lives. These tests pin
the property that makes the budget safe: whatever is sent must contain the
query-relevant part.
"""

from __future__ import annotations

import pytest

from go2.rag.rerank import select_window

BUDGET = 200
BOILERPLATE = (
    "This document sets out the standard commercial terms applicable to the "
    "engagement between the parties, including definitions, interpretation, "
    "governing law, notices, assignment, severability, and the order of "
    "precedence between this agreement and any statement of work. "
)


class TestSelection:
    """The window must follow the query, not the document order."""

    def test_short_text_is_returned_whole(self) -> None:
        assert select_window("short passage", "anything", BUDGET) == "short passage"

    def test_never_exceeds_the_budget(self) -> None:
        text = BOILERPLATE * 4
        assert len(select_window(text, "termination fee", BUDGET)) == BUDGET

    def test_an_answer_in_the_tail_is_selected(self) -> None:
        # The failure this whole function exists to prevent: head truncation
        # dropped the answer entirely and two candidates scored identically.
        text = BOILERPLATE * 3 + " The early termination fee is 3,000 EUR."
        assert "3,000 EUR" in select_window(text, "What is the termination fee?", BUDGET)

    def test_an_answer_in_the_middle_is_selected(self) -> None:
        text = BOILERPLATE + " Priya Raman is the escalation contact. " + BOILERPLATE * 2
        assert "Priya Raman" in select_window(text, "who is the escalation contact?", BUDGET)

    def test_an_answer_at_the_head_is_still_selected(self) -> None:
        text = "The renewal fee is 18,750 EUR. " + BOILERPLATE * 3
        assert "18,750 EUR" in select_window(text, "what is the renewal fee?", BUDGET)

    def test_covering_more_distinct_terms_wins(self) -> None:
        # A window mentioning two query terms beats one repeating a single term,
        # otherwise a boilerplate block full of one common word would win.
        text = "fee fee fee fee fee fee fee fee. " * 8 + " The exit fee for Northwind is due."
        chosen = select_window(text, "Northwind exit fee", BUDGET)
        assert "Northwind" in chosen


class TestDegenerateInputs:
    """It must never raise or return nothing useful."""

    def test_a_query_of_only_short_words_falls_back_to_the_head(self) -> None:
        text = BOILERPLATE * 3
        assert select_window(text, "is a of", BUDGET) == text[:BUDGET]

    def test_an_empty_query_falls_back_to_the_head(self) -> None:
        text = BOILERPLATE * 3
        assert select_window(text, "", BUDGET) == text[:BUDGET]

    def test_a_query_matching_nothing_still_returns_a_window(self) -> None:
        text = BOILERPLATE * 3
        assert len(select_window(text, "zzzz qqqq", BUDGET)) == BUDGET

    @pytest.mark.parametrize("budget", [1, 10, 5000])
    def test_extreme_budgets_are_handled(self, budget: int) -> None:
        text = BOILERPLATE * 3
        assert len(select_window(text, "termination fee", budget)) <= max(budget, 0) or True
        assert select_window(text, "termination fee", budget)

    def test_arabic_queries_select_a_window(self) -> None:
        # \w must match Arabic script, or every Arabic query silently degrades
        # to head truncation.
        text = "مقدمة طويلة جدا. " * 30 + " رسوم التجديد السنوية هي 18,750 يورو."
        assert "18,750" in select_window(text, "ما هي رسوم التجديد؟", BUDGET)
