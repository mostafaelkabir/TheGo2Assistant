# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Markdown extraction tests.

Markdown is the bulk of a typical notes or engineering corpus, so its headings
carry most of the citation value in the whole system.
"""

from __future__ import annotations

from go2.extraction.markdown import extract_markdown
from go2.extraction.registry import find_extractor

EXPECTED_SECTIONS = 2


def _headings(data: bytes) -> list[str | None]:
    return [b.heading for b in extract_markdown(data).blocks]


class TestHeadings:
    """Headings become the citable location."""

    def test_each_section_becomes_its_own_block(self) -> None:
        data = b"# Alpha\nfirst body\n\n# Beta\nsecond body\n"
        blocks = extract_markdown(data).blocks
        assert len(blocks) == EXPECTED_SECTIONS
        assert blocks[0].heading == "Alpha"
        assert blocks[1].heading == "Beta"

    def test_body_text_excludes_the_heading_line(self) -> None:
        blocks = extract_markdown(b"# Alpha\nfirst body\n").blocks
        assert blocks[0].text == "first body"

    def test_all_heading_levels_are_recognised(self) -> None:
        data = b"# One\na\n## Two\nb\n### Three\nc\n###### Six\nd\n"
        assert _headings(data) == ["One", "Two", "Three", "Six"]

    def test_seven_hashes_is_not_a_heading(self) -> None:
        # Markdown tops out at six; more is body text.
        assert _headings(b"####### Seven\nbody\n") == [None]

    def test_text_before_any_heading_is_kept(self) -> None:
        blocks = extract_markdown(b"intro paragraph\n\n# Alpha\nbody\n").blocks
        assert blocks[0].heading is None
        assert "intro" in blocks[0].text

    def test_inline_markup_is_stripped_from_the_citation(self) -> None:
        assert _headings(b"# **Bold** and `code`\nbody\n") == ["Bold and code"]

    def test_links_reduce_to_their_text(self) -> None:
        assert _headings(b"# See [the docs](https://example.com)\nbody\n") == ["See the docs"]

    def test_closing_hashes_are_stripped(self) -> None:
        assert _headings(b"## Alpha ##\nbody\n") == ["Alpha"]

    def test_setext_headings_are_recognised(self) -> None:
        assert _headings(b"Alpha\n=====\nbody\n") == ["Alpha"]

    def test_an_empty_document_yields_nothing(self) -> None:
        assert extract_markdown(b"").blocks == []

    def test_a_heading_with_no_body_is_dropped(self) -> None:
        # An empty section would only add a chunk with nothing to retrieve.
        assert _headings(b"# Alpha\n\n# Beta\nbody\n") == ["Beta"]


class TestCodeFences:
    """A `#` inside code is a comment, not a heading."""

    def test_hashes_inside_a_fence_are_not_headings(self) -> None:
        data = b"# Real\nbody\n\n```bash\n# not a heading\nls -la\n```\nmore body\n"
        assert _headings(data) == ["Real"]

    def test_fenced_content_is_preserved(self) -> None:
        data = b"# Real\n```python\n# comment\nx = 1\n```\n"
        assert "x = 1" in extract_markdown(data).blocks[0].text

    def test_tilde_fences_are_handled(self) -> None:
        data = b"# Real\n~~~\n# not a heading\n~~~\n"
        assert _headings(data) == ["Real"]

    def test_a_heading_after_a_closed_fence_still_counts(self) -> None:
        data = b"# One\n```\n# comment\n```\n# Two\nbody\n"
        assert _headings(data) == ["One", "Two"]


class TestRegistry:
    """Markdown dispatches to the structured extractor, not plain text."""

    def test_md_uses_the_markdown_extractor(self) -> None:
        assert find_extractor("notes.md") is extract_markdown

    def test_markdown_mime_uses_it_too(self) -> None:
        assert find_extractor("notes", "text/markdown") is extract_markdown

    def test_plain_text_does_not(self) -> None:
        # A .txt file has no heading syntax to honour.
        assert find_extractor("notes.txt") is not extract_markdown
