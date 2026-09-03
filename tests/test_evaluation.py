# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Eval harness tests.

The harness is what catches retrieval regressions, so its own failure modes
matter: a malformed file must be rejected loudly rather than silently
evaluating zero cases and reporting success.
"""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING

import pytest

from go2.evaluation import (
    Case,
    EvalFileError,
    Outcome,
    TenantMismatchError,
    _canon,
    load_cases,
    summarise,
)
from go2.storage.repository import canonical_title

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
        cases = load_cases(path).cases
        assert cases[0].question == "how much?"
        assert cases[0].expect_documents == ["Contract"]
        assert cases[0].expect_text is None

    def test_a_case_may_accept_several_documents(self, tmp_path: Path) -> None:
        # A question often has more than one right source; insisting on one
        # invites tuning the eval until it passes.
        path = tmp_path / "q.yaml"
        path.write_text("- question: how?\n  expect_document:\n    - Runbook\n    - Overview\n")
        assert load_cases(path).cases[0].expect_documents == ["Runbook", "Overview"]

    def test_a_refusal_case_needs_no_document(self, tmp_path: Path) -> None:
        path = tmp_path / "q.yaml"
        path.write_text("- question: unrelated?\n  expect_no_answer: true\n")
        case = load_cases(path).cases[0]
        assert case.expect_no_answer
        assert case.expect_documents == []

    def test_reads_the_optional_text_expectation(self, tmp_path: Path) -> None:
        path = tmp_path / "q.yaml"
        path.write_text('- question: q\n  expect_document: D\n  expect_text: "507"\n')
        assert load_cases(path).cases[0].expect_text == "507"

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


class TestSuiteTenant:
    """A question set may name the workspace it was written for."""

    def test_a_bare_list_still_loads(self, tmp_path: Path) -> None:
        # Existing files have no `tenant` key and must keep working.
        path = tmp_path / "e.yaml"
        path.write_text("- question: Q\n  expect_document: D\n")
        suite = load_cases(path)
        assert suite.tenant is None
        assert len(suite.cases) == 1

    def test_a_mapping_carries_the_tenant(self, tmp_path: Path) -> None:
        path = tmp_path / "e.yaml"
        path.write_text("tenant: dawan\ncases:\n  - question: Q\n    expect_document: D\n")
        suite = load_cases(path)
        assert suite.tenant == "dawan"
        assert suite.cases[0].question == "Q"

    def test_a_mapping_without_cases_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "e.yaml"
        path.write_text("tenant: dawan\n")
        with pytest.raises(EvalFileError):
            load_cases(path)

    def test_the_mismatch_error_names_both_workspaces_and_the_fix(self) -> None:
        message = str(TenantMismatchError("dawan", "local"))
        assert "dawan" in message
        assert "local" in message
        assert "GO2_TENANT=dawan" in message


class TestUnicodeTitles:
    """A title matches the document it names, whatever Unicode form it is in."""

    # macOS stores filenames decomposed; a name typed into YAML is composed.
    # They render identically and compare unequal, so an eval case could fail
    # against the very document it named -- an eval that lies about retrieval.
    COMPOSED = unicodedata.normalize("NFC", "النموذج الأولي للمنتج")
    DECOMPOSED = unicodedata.normalize("NFD", "النموذج الأولي للمنتج")

    def test_the_two_forms_really_do_differ(self) -> None:
        # Guards the test itself: if these were equal the rest proves nothing.
        assert self.COMPOSED != self.DECOMPOSED

    def test_a_composed_expectation_matches_a_decomposed_title(self) -> None:
        case = Case(question="Q", expect_documents=[self.COMPOSED])
        assert _canon(case.expect_documents[0]) in _canon(f"{self.DECOMPOSED}.pdf")

    def test_a_decomposed_expectation_matches_a_composed_title(self) -> None:
        case = Case(question="Q", expect_documents=[self.DECOMPOSED])
        assert _canon(case.expect_documents[0]) in _canon(f"{self.COMPOSED}.pdf")

    def test_matching_is_still_case_insensitive(self) -> None:
        assert _canon("RESUME") in _canon("my_resume_context.md")

    def test_canonical_title_is_idempotent(self) -> None:
        once = canonical_title(self.DECOMPOSED)
        assert canonical_title(once) == once

    def test_canonical_title_does_not_fold_compatibility_forms(self) -> None:
        # NFKC would rewrite this to "1/2"; a filename is not ours to rewrite.
        assert canonical_title("report½.pdf") == "report½.pdf"
