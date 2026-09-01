# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Chunking tests, with emphasis on the invariants that protect citations."""

from __future__ import annotations

import pytest

from go2.extraction.base import Block
from go2.rag.chunking import Chunk, chunk_blocks

SMALL_LIMIT = 100
SMALL_OVERLAP = 20


def _texts(chunks: list[Chunk]) -> list[str]:
    return [c.text for c in chunks]


class TestLocationIntegrity:
    """A chunk must be citable to exactly one place."""

    def test_blocks_on_different_pages_are_never_merged(self) -> None:
        blocks = [Block(text="Short one.", page=1), Block(text="Short two.", page=2)]
        chunks = chunk_blocks(blocks)
        # Both would comfortably fit in one chunk; they must not be combined,
        # because the result could only be cited to one of the two pages.
        assert [c.page for c in chunks] == [1, 2]

    def test_blocks_on_different_slides_are_never_merged(self) -> None:
        blocks = [Block(text="Alpha.", slide=1), Block(text="Beta.", slide=3)]
        assert [c.slide for c in chunk_blocks(blocks)] == [1, 3]

    def test_unlocated_blocks_merge_freely(self) -> None:
        blocks = [Block(text="One."), Block(text="Two."), Block(text="Three.")]
        chunks = chunk_blocks(blocks)
        assert len(chunks) == 1
        assert "One." in chunks[0].text
        assert "Three." in chunks[0].text

    def test_page_survives_a_split_within_one_page(self) -> None:
        blocks = [Block(text="word " * 200, page=7)]
        chunks = chunk_blocks(blocks, max_chars=SMALL_LIMIT, overlap_chars=SMALL_OVERLAP)
        assert len(chunks) > 1
        assert {c.page for c in chunks} == {7}

    def test_blocks_under_different_headings_are_never_merged(self) -> None:
        # A Word document has no page numbers, so the heading is the only
        # coordinate a citation has. Merging sections files the answer under
        # the wrong one -- caught in real search output, where a remote-work
        # answer was cited as "Expense Policy".
        blocks = [
            Block(text="Receipts above 50 USD.", heading="Expenses"),
            Block(text="Engineers may work remotely.", heading="Remote Work"),
        ]
        chunks = chunk_blocks(blocks)
        assert [c.heading for c in chunks] == ["Expenses", "Remote Work"]
        remote = next(c for c in chunks if "remotely" in c.text)
        assert remote.heading == "Remote Work"

    def test_heading_propagates_to_every_chunk_of_a_group(self) -> None:
        blocks = [
            Block(text="a " * 100, heading="Payment Terms"),
            Block(text="b " * 100, heading="Payment Terms"),
        ]
        chunks = chunk_blocks(blocks, max_chars=SMALL_LIMIT, overlap_chars=SMALL_OVERLAP)
        assert {c.heading for c in chunks} == {"Payment Terms"}


class TestSizing:
    """Size bounds and ordinals."""

    def test_ordinals_are_contiguous_from_zero(self) -> None:
        blocks = [Block(text=f"Sentence {i}. " * 40, page=i) for i in range(1, 4)]
        chunks = chunk_blocks(blocks, max_chars=SMALL_LIMIT, overlap_chars=SMALL_OVERLAP)
        assert [c.ordinal for c in chunks] == list(range(len(chunks)))

    def test_max_chars_is_a_hard_bound_even_with_overlap(self) -> None:
        # Overlap is prepended after sizing, so it must be trimmed to fit
        # rather than pushing the chunk past the stated bound.
        blocks = [Block(text="alpha beta gamma delta epsilon " * 40)]
        chunks = chunk_blocks(blocks, max_chars=SMALL_LIMIT, overlap_chars=SMALL_OVERLAP)
        assert len(chunks) > 1
        assert all(len(c.text) <= SMALL_LIMIT for c in chunks)

    def test_oversized_block_is_split(self) -> None:
        chunks = chunk_blocks(
            [Block(text="alpha beta gamma delta. " * 50)],
            max_chars=SMALL_LIMIT,
            overlap_chars=SMALL_OVERLAP,
        )
        assert len(chunks) > 1

    def test_a_block_with_no_boundaries_at_all_still_splits(self) -> None:
        # No spaces, no punctuation, no newlines: the last-resort hard slice.
        chunks = chunk_blocks(
            [Block(text="x" * 500)], max_chars=SMALL_LIMIT, overlap_chars=SMALL_OVERLAP
        )
        assert len(chunks) > 1
        assert all(len(c.text) <= SMALL_LIMIT for c in chunks)

    def test_prefers_paragraph_boundaries_over_mid_sentence_cuts(self) -> None:
        text = "First paragraph here.\n\nSecond paragraph here.\n\nThird paragraph here."
        chunks = chunk_blocks([Block(text=text)], max_chars=30, overlap_chars=0)
        assert all(not c.text.startswith(" ") for c in chunks)
        assert "First paragraph here." in chunks[0].text

    def test_splits_on_arabic_sentence_punctuation(self) -> None:
        # The Arabic question mark differs from the Latin one; splitting must
        # recognise it or Arabic prose degrades to hard character slicing.
        text = "ما هي شروط الدفع؟ " * 20
        chunks = chunk_blocks([Block(text=text)], max_chars=SMALL_LIMIT, overlap_chars=0)
        assert len(chunks) > 1
        assert all(not c.text.startswith("؟") for c in chunks)


class TestOverlap:
    """Overlap keeps a fact that straddles a boundary findable."""

    def test_overlap_repeats_the_previous_tail(self) -> None:
        blocks = [Block(text="alpha beta gamma delta epsilon zeta eta theta iota kappa " * 6)]
        chunks = chunk_blocks(blocks, max_chars=120, overlap_chars=40)
        assert len(chunks) > 1
        tail_words = set(chunks[0].text.split()[-3:])
        assert tail_words & set(chunks[1].text.split())

    def test_zero_overlap_produces_disjoint_chunks(self) -> None:
        blocks = [Block(text="one two three four five six seven eight nine ten. " * 10)]
        chunks = chunk_blocks(blocks, max_chars=120, overlap_chars=0)
        assert len(chunks) > 1
        # With no overlap the total length must not exceed the source length.
        assert sum(len(c.text) for c in chunks) <= len(blocks[0].text)

    def test_overlap_must_be_smaller_than_the_chunk(self) -> None:
        with pytest.raises(ValueError, match="must be smaller"):
            chunk_blocks([Block(text="x")], max_chars=100, overlap_chars=100)


class TestEdgeCases:
    """Degenerate inputs."""

    def test_no_blocks_yields_no_chunks(self) -> None:
        assert chunk_blocks([]) == []

    def test_whitespace_only_blocks_are_dropped(self) -> None:
        assert chunk_blocks([Block(text="   \n\n  "), Block(text="\t")]) == []

    def test_content_is_not_lost(self) -> None:
        blocks = [Block(text=f"unique{i} " * 20, page=i) for i in range(1, 5)]
        joined = " ".join(_texts(chunk_blocks(blocks, max_chars=SMALL_LIMIT, overlap_chars=0)))
        for i in range(1, 5):
            assert f"unique{i}" in joined
