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

import unicodedata
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import yaml

from go2.config import get_settings
from go2.rag.retrieval import SearchOptions, search
from go2.storage.db import connect
from go2.tenancy import resolve_tenant_id

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_LIMIT = 5


@dataclass(frozen=True, slots=True)
class Case:
    """One question and what should answer it.

    A case with ``expect_no_answer`` asserts the opposite: that the documents
    do *not* cover the question and the system says so. For an assistant that
    must answer only from recorded data, refusing correctly is as much a
    feature as retrieving correctly, and only measuring the positive half
    leaves the abstention threshold unchecked.
    """

    question: str
    # Any one of these titles satisfies the case. Real questions often have
    # more than one right source -- an entry-point document and the runbook it
    # points at are both correct answers to "how do I run this". Forcing a
    # single expected title invites tuning the eval until it passes, which is
    # how an eval quietly stops measuring anything.
    expect_documents: list[str] = field(default_factory=list)
    expect_text: str | None = None
    expect_no_answer: bool = False

    @property
    def expect_document(self) -> str:
        """The first acceptable title, for reporting."""
        return " or ".join(self.expect_documents) if self.expect_documents else ""


@dataclass(frozen=True, slots=True)
class Outcome:
    """What retrieval actually did with one case."""

    case: Case
    rank: int | None
    top_citation: str
    top_score: float
    text_found: bool
    returned: list[str]
    sufficient: bool = True

    @property
    def passed(self) -> bool:
        """Whether the system did what the case expects.

        For an answerable case, retrieving the right document is not enough:
        the evidence gate must also accept it. Scoring on retrieval alone
        reports a pass for a question the assistant would actually decline to
        answer, which is precisely the silent gap this harness exists to close.
        """
        if self.case.expect_no_answer:
            return not self.sufficient
        return self.rank is not None and self.expect_text_ok and self.sufficient

    @property
    def expect_text_ok(self) -> bool:
        """Whether the expected snippet requirement is satisfied."""
        return self.case.expect_text is None or self.text_found


class TenantMismatchError(ValueError):
    """Raised when a question set is run against the wrong workspace."""

    def __init__(self, wanted: str, active: str) -> None:
        """Name both workspaces and the command that fixes it."""
        super().__init__(
            f"this question set was written for the {wanted!r} workspace, but "
            f"{active!r} is active. Its questions ask about documents {active!r} "
            f"may not hold, so the score would be meaningless rather than bad. "
            f"Run `GO2_TENANT={wanted} go2 evaluate ...`, or remove the `tenant:` "
            f"key to run it anywhere."
        )


class EvalFileError(ValueError):
    """Raised when the eval file cannot be used."""


@dataclass(frozen=True, slots=True)
class Suite:
    """A question set, and the workspace it was written against.

    ``tenant`` exists because the failure it prevents is silent. The questions
    ask about specific documents, so running a set against the wrong workspace
    does not error -- it returns a plausible, terrible score. The first run of
    the original set against `dawan` scored 5/17 and looked like a retrieval
    regression; it was a set asking about documents that workspace has never
    held. A number that wrong is more dangerous than a crash.
    """

    cases: list[Case]
    tenant: str | None = None


def load_cases(path: Path) -> Suite:
    """Read a question set from a YAML file.

    Accepts either a bare list of cases, or a mapping with ``tenant`` and
    ``cases`` keys. The bare list stays valid because a set that does not name
    a workspace is not wrong, only unguarded.

    Args:
        path: File containing the cases.

    Returns:
        The parsed suite.

    Raises:
        EvalFileError: If the file is missing, malformed, or has no cases.
    """
    if not path.is_file():
        msg = f"no eval file at {path}"
        raise EvalFileError(msg)

    loaded: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    tenant: str | None = None
    if isinstance(loaded, dict):
        tenant = None if loaded.get("tenant") is None else str(loaded["tenant"])
        loaded = loaded.get("cases")
    if not isinstance(loaded, list) or not loaded:
        msg = f"{path} should contain a non-empty list of cases"
        raise EvalFileError(msg)

    cases: list[Case] = []
    for index, raw in enumerate(loaded, start=1):
        if not isinstance(raw, dict) or "question" not in raw:
            msg = f"case {index} in {path} needs a 'question'"
            raise EvalFileError(msg)
        refuses = bool(raw.get("expect_no_answer", False))
        expected = raw.get("expect_document")
        titles = (
            [str(t) for t in expected]
            if isinstance(expected, list)
            else ([str(expected)] if expected is not None else [])
        )
        if not refuses and not titles:
            msg = f"case {index} in {path} needs 'expect_document' or 'expect_no_answer'"
            raise EvalFileError(msg)
        cases.append(
            Case(
                question=str(raw["question"]),
                expect_documents=titles,
                expect_text=None if raw.get("expect_text") is None else str(raw["expect_text"]),
                expect_no_answer=refuses,
            )
        )
    return Suite(cases=cases, tenant=tenant)


def _canon(value: str) -> str:
    """Casefold and Unicode-normalise, so an Arabic title matches what it names."""
    return unicodedata.normalize("NFC", value).casefold()


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

    threshold = get_settings().min_evidence_score
    sufficient = bool(hits) and hits[0].score >= threshold

    rank: int | None = None
    text_found = False
    for position, hit in enumerate(hits, start=1):
        if any(_canon(t) in _canon(hit.title) for t in case.expect_documents):
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
        sufficient=sufficient,
    )


def run_all(cases: list[Case], *, limit: int = DEFAULT_LIMIT) -> list[Outcome]:
    """Run every case against the current index."""
    tenant_id = resolve_tenant_id()
    return [run_case(case, tenant_id=tenant_id, limit=limit) for case in cases]


def summarise(outcomes: list[Outcome]) -> dict[str, Any]:
    """Aggregate outcomes into headline numbers.

    Returns:
        Counts plus mean reciprocal rank, which distinguishes "found it first"
        from "found it fourth" -- a distinction plain accuracy hides.
    """
    answerable = [o for o in outcomes if not o.case.expect_no_answer]
    reciprocal = [1.0 / o.rank for o in answerable if o.rank is not None]
    refusals = [o for o in outcomes if o.case.expect_no_answer]
    return {
        "total": len(outcomes),
        "passed": sum(1 for o in outcomes if o.passed),
        "top1": sum(1 for o in answerable if o.rank == 1),
        # MRR is only meaningful over questions that have an answer.
        "mrr": (sum(reciprocal) / len(answerable)) if answerable else 0.0,
        "refusals": len(refusals),
        "refused_correctly": sum(1 for o in refusals if o.passed),
        # The margin between the weakest accepted answer and the strongest
        # wrongly accepted refusal is how much room the threshold actually has.
        "min_accepted": min((o.top_score for o in answerable if o.passed), default=0.0),
        "max_refused": max((o.top_score for o in refusals), default=0.0),
    }
