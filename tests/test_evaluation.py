# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Eval harness tests.

The harness is what catches retrieval regressions, so its own failure modes
matter: a malformed file must be rejected loudly rather than silently
evaluating zero cases and reporting success.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from go2.evaluation import Case, EvalFileError, Outcome, load_cases, summarise

if TYPE_CHECKING:
    from pathlib import Path

EXPECTED_TWO = 2


def _outcome(rank: int | None, *, expect_text: str | None = None, found: bool = False) -> Outcome:
    return Outcome(
        case=Case(question="q", expect_documents=["doc"], expect_text=expect_text),
        rank=rank,
        top_citation="doc",
        top_score=1.0,
        text_found=found,
        returned=["doc"],
    )


class TestLoading:
    """A broken eval file must fail loudly."""

    def test_reads_cases(self, tmp_path: Path) -> None:
        path = tmp_path / "q.yaml"
        path.write_text("- question: how much?\n  expect_document: Contract\n")
        cases = load_cases(path)
        assert cases[0].question == "how much?"
        assert cases[0].expect_documents == ["Contract"]
        assert cases[0].expect_text is None

    def test_a_case_may_accept_several_documents(self, tmp_path: Path) -> None:
        # A question often has more than one right source; insisting on one
        # invites tuning the eval until it passes.
        path = tmp_path / "q.yaml"
        path.write_text("- question: how?\n  expect_document:\n    - Runbook\n    - Overview\n")
        assert load_cases(path)[0].expect_documents == ["Runbook", "Overview"]

    def test_a_refusal_case_needs_no_document(self, tmp_path: Path) -> None:
        path = tmp_path / "q.yaml"
        path.write_text("- question: unrelated?\n  expect_no_answer: true\n")
        case = load_cases(path)[0]
        assert case.expect_no_answer
        assert case.expect_documents == []

    def test_reads_the_optional_text_expectation(self, tmp_path: Path) -> None:
        path = tmp_path / "q.yaml"
        path.write_text('- question: q\n  expect_document: D\n  expect_text: "507"\n')
        assert load_cases(path)[0].expect_text == "507"

    def test_a_missing_file_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(EvalFileError, match="no eval file"):
            load_cases(tmp_path / "absent.yaml")

    def test_an_empty_file_is_an_error(self, tmp_path: Path) -> None:
        # Zero cases passing is not the same as passing, and must not look
        # like a green run.
        path = tmp_path / "q.yaml"
        path.write_text("[]\n")
        with pytest.raises(EvalFileError, match="non-empty"):
            load_cases(path)

    def test_a_case_missing_its_expectation_is_an_error(self, tmp_path: Path) -> None:
        path = tmp_path / "q.yaml"
        path.write_text("- question: only a question\n")
        with pytest.raises(EvalFileError, match="expect_document"):
            load_cases(path)


class TestOutcome:
    """Pass means the document was found and any required text with it."""

    def test_found_at_any_rank_passes(self) -> None:
        assert _outcome(3).passed

    def test_not_found_fails(self) -> None:
        assert not _outcome(None).passed

    def test_a_text_expectation_must_also_be_met(self) -> None:
        # Returning the right file is not enough when the answer lives in one
        # section of it.
        assert not _outcome(1, expect_text="507", found=False).passed
        assert _outcome(1, expect_text="507", found=True).passed


class TestSummary:
    """MRR distinguishes rank 1 from rank 4; accuracy does not."""

    def test_counts_and_top1(self) -> None:
        stats = summarise([_outcome(1), _outcome(3), _outcome(None)])
        assert stats["total"] == 3
        assert stats["passed"] == EXPECTED_TWO
        assert stats["top1"] == 1

    def test_mrr_rewards_a_better_rank(self) -> None:
        better = summarise([_outcome(1)])["mrr"]
        worse = summarise([_outcome(4)])["mrr"]
        assert better > worse

    def test_no_outcomes_is_zero_not_a_crash(self) -> None:
        assert summarise([])["mrr"] == 0.0
