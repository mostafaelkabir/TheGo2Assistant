# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Markdown extraction.

Markdown carries its own structure, and discarding it costs twice: a citation
degrades to a bare filename with no section, and chunking loses the natural
split points. Headings are parsed into ``Block.heading``, which makes them part
of the citable location and stops unrelated sections merging into one chunk.

Fenced code blocks are tracked so a ``#`` comment inside a shell snippet is not
mistaken for a heading -- a real hazard in engineering notes.
"""

from __future__ import annotations

import re

from go2.extraction.base import Block, Extracted

_ATX_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
# Setext underline: a line of === or --- directly under heading text.
_SETEXT = re.compile(r"^\s*(=+|-{2,})\s*$")


def _clean(title: str) -> str:
    """Strip inline markup that would only add noise to a citation."""
    title = re.sub(r"[*_`]", "", title)
    title = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", title)  # links -> their text
    return title.strip()


def extract_markdown(data: bytes) -> Extracted:
    """Extract markdown as one block per heading section.

    Args:
        data: Raw markdown bytes, decoded as UTF-8 with replacement.

    Returns:
        One block per section, tagged with the heading it falls under. Text
        before any heading is emitted with no heading, as it belongs to the
        document itself.
    """
    lines = data.decode("utf-8", errors="replace").splitlines()

    blocks: list[Block] = []
    heading: str | None = None
    body: list[str] = []
    in_fence = False

    def flush() -> None:
        text = "\n".join(body).strip()
        if text:
            blocks.append(Block(text=text, heading=heading))
        body.clear()

    skip_underline = False

    for index, line in enumerate(lines):
        if skip_underline:
            skip_underline = False
            continue

        if _FENCE.match(line):
            in_fence = not in_fence
            body.append(line)
            continue

        if in_fence:
            body.append(line)
            continue

        match = _ATX_HEADING.match(line)
        if match:
            flush()
            heading = _clean(match.group(2))
            continue

        # A setext heading is text underlined by === or ---, so it is only
        # recognisable by looking one line ahead.
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if line.strip() and _SETEXT.match(following):
            flush()
            heading = _clean(line)
            skip_underline = True
            continue

        body.append(line)

    flush()
    return Extracted(blocks=blocks)
