# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""The egress boundary.

Everything that leaves this machine passes through here. Keeping it in one
module is the point: a control spread across call sites is one that a new code
path silently bypasses.

What crosses the boundary today is larger than a chat message. With a hosted
provider configured, *every chunk of every document* is sent at ingest time,
plus each query and the candidate passages reranked for it. That is the surface
this guards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from go2.config import get_settings
from go2.security.pii import detect, redact, summarise

if TYPE_CHECKING:
    from collections.abc import Sequence


class PiiBlockedError(RuntimeError):
    """Raised when policy forbids sending text that contains PII."""

    def __init__(self, counts: dict[str, int]) -> None:
        """Name what was found and both ways to proceed."""
        found = ", ".join(f"{n} {kind}" for kind, n in sorted(counts.items()))
        super().__init__(
            f"blocked by pii_policy=block: text contains {found}. "
            f"Set GO2_PII_POLICY=redact to mask it, or GO2_EMBEDDING_PROVIDER=local "
            f"to keep everything on this machine."
        )


@dataclass(frozen=True, slots=True)
class Screened:
    """Text cleared to leave, and what was removed from it."""

    texts: list[str]
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def redacted_any(self) -> bool:
        """Whether anything was masked."""
        return bool(self.counts)


def screen(texts: Sequence[str]) -> Screened:
    """Apply the configured PII policy to text about to leave the machine.

    Args:
        texts: The texts to screen.

    Returns:
        The texts as they should be sent, and a count of what was masked.

    Raises:
        PiiBlockedError: When policy is ``block`` and PII was found.
    """
    policy = get_settings().pii_policy
    if policy == "allow":
        return Screened(texts=list(texts))

    if policy == "block":
        counts: dict[str, int] = {}
        for text in texts:
            for kind, number in summarise(detect(text)).items():
                counts[kind] = counts.get(kind, 0) + number
        if counts:
            raise PiiBlockedError(counts)
        return Screened(texts=list(texts))

    cleaned: list[str] = []
    totals: dict[str, int] = {}
    for text in texts:
        masked, findings = redact(text)
        cleaned.append(masked)
        for kind, number in summarise(findings).items():
            totals[kind] = totals.get(kind, 0) + number
    return Screened(texts=cleaned, counts=totals)
