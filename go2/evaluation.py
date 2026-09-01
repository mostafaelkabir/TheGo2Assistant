# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Repeatable retrieval checks.

Ad-hoc searching tells you whether retrieval works *today*, for the question
you happened to think of. It does not tell you whether a chunking change, a
provider switch, or a new reranker quietly broke something that used to work --
and retrieval regressions are silent by nature: the system still returns
confident-looking passages, just the wrong ones.

An eval file turns "does it still work" into a command. Each case names a
question and the document that should answer it; the rank at which that
document actually appears is the measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import yaml

from go2.rag.retrieval import SearchOptions, search
from go2.storage.db import connect, default_tenant_id

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_LIMIT = 5


@dataclass(frozen=True, slots=True)
class Case:
    """One question and what should answer it."""

    question: str
    expect_document: str
    expect_text: str | None = None


@dataclass(frozen=True, slots=True)
class Outcome:
    """What retrieval actually did with one case."""

    case: Case
    rank: int | None
    top_citation: str
    top_score: float
    text_found: bool
    returned: list[str]

    @property
    def passed(self) -> bool:
        """Whether the expected document came back, and any expected text with it."""
        return self.rank is not None and (self.expect_text_ok)

    @property
    def expect_text_ok(self) -> bool:
        """Whether the expected snippet requirement is satisfied."""
        return self.case.expect_text is None or self.text_found


class EvalFileError(ValueError):
    """Raised when the eval file cannot be used."""


def load_cases(path: Path) -> list[Case]:
    """Read cases from a YAML file.

    Args:
        path: File containing a list of ``{question, expect_document}`` maps.

    Returns:
        The parsed cases.

    Raises:
        EvalFileError: If the file is missing, malformed, or has no cases.
    """
    if not path.is_file():
        msg = f"no eval file at {path}"
        raise EvalFileError(msg)

    loaded: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, list) or not loaded:
        msg = f"{path} should contain a non-empty list of cases"
        raise EvalFileError(msg)

    cases: list[Case] = []
    for index, raw in enumerate(loaded, start=1):
        if not isinstance(raw, dict) or "question" not in raw or "expect_document" not in raw:
            msg = f"case {index} in {path} needs both 'question' and 'expect_document'"
            raise EvalFileError(msg)
        cases.append(
            Case(
                question=str(raw["question"]),
                expect_document=str(raw["expect_document"]),
                expect_text=None if raw.get("expect_text") is None else str(raw["expect_text"]),
            )
        )
    return cases


def run_case(case: Case, *, tenant_id: str, limit: int = DEFAULT_LIMIT) -> Outcome:
    """Search for one case and record where the expected document landed.

    Args:
        case: The question and its expected source.
        tenant_id: Owning tenant.
        limit: How many hits to consider. A document at rank 4 is a weaker
            result than one at rank 1, so the rank is reported rather than a
            bare pass/fail.

    Returns:
        The outcome, including the rank of the expected document.
    """
    with connect() as conn:
        hits = search(
            conn, tenant_id=tenant_id, query=case.question, options=SearchOptions(limit=limit)
        )

    rank: int | None = None
    text_found = False
    for position, hit in enumerate(hits, start=1):
        if case.expect_document.lower() in hit.title.lower():
            if rank is None:
                rank = position
            if case.expect_text and case.expect_text.lower() in hit.text.lower():
                text_found = True

    return Outcome(
        case=case,
        rank=rank,
        top_citation=hits[0].citation() if hits else "",
        top_score=hits[0].score if hits else 0.0,
        text_found=text_found,
        returned=[h.title for h in hits],
    )


def run_all(cases: list[Case], *, limit: int = DEFAULT_LIMIT) -> list[Outcome]:
    """Run every case against the current index."""
    tenant_id = default_tenant_id()
    return [run_case(case, tenant_id=tenant_id, limit=limit) for case in cases]


def summarise(outcomes: list[Outcome]) -> dict[str, Any]:
    """Aggregate outcomes into headline numbers.

    Returns:
        Counts plus mean reciprocal rank, which distinguishes "found it first"
        from "found it fourth" -- a distinction plain accuracy hides.
    """
    passed = [o for o in outcomes if o.passed]
    reciprocal = [1.0 / o.rank for o in outcomes if o.rank is not None]
    return {
        "total": len(outcomes),
        "passed": len(passed),
        "top1": sum(1 for o in outcomes if o.rank == 1),
        "mrr": (sum(reciprocal) / len(outcomes)) if outcomes else 0.0,
    }
