# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Structure-aware chunking.

Two decisions shape this module:

Sizing is in **characters, not tokens**. The corpus is mixed Arabic/English, and
a token count borrowed from a different model's tokenizer misestimates one
script or the other badly -- English text would chunk near the target while
Arabic chunked far under it. Characters are consistent across both, and the
embedding model's real limit is far enough away that an approximate budget is
safe.

Blocks from **different locations are never merged**. A chunk spanning pages 3
and 4 can only be cited as one of them, and a citation that points a reader at
the wrong page is worse than a slightly smaller chunk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from go2.extraction.base import Block

# Separator used when joining pieces inside one chunk. Its length is part of
# the size arithmetic below, so it lives in a constant.
_JOIN = "\n\n"

# Paragraph break, then sentence end, then any newline: the order walks from
# most to least semantically meaningful split point.
_SPLIT_PATTERNS = (
    re.compile(r"\n\s*\n"),
    re.compile("(?<=[.!?\u061f\u06d4])\\s+"),  # \u061f Arabic ?, \u06d4 Arabic full stop
    re.compile(r"\n"),
)


@dataclass(frozen=True, slots=True)
class Chunk:
    """A unit of retrievable text with the location it can be cited to."""

    text: str
    ordinal: int
    page: int | None = None
    slide: int | None = None
    heading: str | None = None


def _split_oversized(text: str, limit: int) -> list[str]:
    """Break one long run of text into pieces under ``limit`` characters.

    Tries progressively weaker boundaries and only slices mid-word as a last
    resort, so a chunk rarely ends mid-sentence.
    """
    if len(text) <= limit:
        return [text]

    for pattern in _SPLIT_PATTERNS:
        parts = [p for p in pattern.split(text) if p.strip()]
        if len(parts) < 2:  # noqa: PLR2004 -- a single part means this boundary did not split.
            continue
        pieces: list[str] = []
        current = ""
        for part in parts:
            candidate = f"{current}\n{part}" if current else part
            if len(candidate) > limit and current:
                pieces.append(current)
                current = part
            else:
                current = candidate
        if current:
            pieces.append(current)
        # A part may still exceed the limit on its own; recurse on the rest.
        if all(len(p) <= limit for p in pieces):
            return pieces
        return [piece for p in pieces for piece in _split_oversized(p, limit)]

    return [text[i : i + limit] for i in range(0, len(text), limit)]


def _location(block: Block) -> tuple[int | None, int | None]:
    return (block.page, block.slide)


def _overlap_tail(text: str, overlap: int) -> str:
    """Return the trailing ``overlap`` characters, snapped to a word boundary."""
    if overlap <= 0 or len(text) <= overlap:
        return ""
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1 :] if space != -1 else tail


def _group_by_location(blocks: Iterable[Block]) -> list[list[Block]]:
    groups: list[list[Block]] = []
    previous: tuple[int | None, int | None] | None = None
    for block in blocks:
        location = _location(block)
        if previous is None or location != previous:
            groups.append([block])
            previous = location
        else:
            groups[-1].append(block)
    return groups


def chunk_blocks(
    blocks: Sequence[Block],
    *,
    max_chars: int = 3200,
    overlap_chars: int = 400,
) -> list[Chunk]:
    """Turn extracted blocks into retrievable chunks.

    Args:
        blocks: Extracted prose blocks, in document order.
        max_chars: Hard upper bound on chunk length, overlap included.
        overlap_chars: Characters of the previous chunk to repeat at the start
            of the next one, so a fact split across a boundary stays findable.

    Returns:
        Chunks in document order, each numbered by its ``ordinal``.

    Raises:
        ValueError: If ``overlap_chars`` is not smaller than ``max_chars``.
    """
    if overlap_chars >= max_chars:
        msg = f"overlap_chars ({overlap_chars}) must be smaller than max_chars ({max_chars})"
        raise ValueError(msg)

    chunks: list[Chunk] = []
    ordinal = 0

    for group in _group_by_location(blocks):
        page, slide = _location(group[0])
        # The heading of the first block that has one describes the group.
        heading = next((b.heading for b in group if b.heading), None)

        buffer = ""
        for block in group:
            for piece in _split_oversized(block.text.strip(), max_chars):
                candidate = f"{buffer}{_JOIN}{piece}" if buffer else piece
                if len(candidate) > max_chars and buffer:
                    chunks.append(
                        Chunk(text=buffer, ordinal=ordinal, page=page, slide=slide, heading=heading)
                    )
                    ordinal += 1
                    # Trim the carried tail to whatever room the next piece
                    # leaves, so max_chars stays a hard bound rather than one
                    # the overlap quietly overshoots.
                    tail = _overlap_tail(buffer, overlap_chars)
                    room = max_chars - len(piece) - len(_JOIN)
                    tail = tail[len(tail) - room :] if 0 < room < len(tail) else tail
                    buffer = f"{tail}{_JOIN}{piece}" if room > 0 and tail else piece
                else:
                    buffer = candidate
        if buffer.strip():
            chunks.append(
                Chunk(text=buffer, ordinal=ordinal, page=page, slide=slide, heading=heading)
            )
            ordinal += 1

    return chunks
