# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Types shared by every extractor.

An extractor turns raw bytes into ``Extracted``. It never chunks and never
embeds -- those are separate stages, so a single ingestion pipeline can serve
uploads and every connector alike.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# A page whose text layer yields fewer than this many non-whitespace characters
# is treated as scanned. Chosen to survive stray headers and page numbers that
# a scanner's text layer sometimes carries while the body remains an image.
MIN_CHARS_PER_TEXT_PAGE = 24


@dataclass(frozen=True, slots=True)
class Block:
    """A contiguous run of prose with the location it came from.

    Location fields are mutually exclusive in practice: a PDF block carries
    ``page``, a slide block carries ``slide``. They exist on one type so
    chunking and citation do not need to branch per source format.
    """

    text: str
    page: int | None = None
    slide: int | None = None
    heading: str | None = None


@dataclass(frozen=True, slots=True)
class SheetTable:
    """One worksheet, kept whole.

    Spreadsheets are never chunked as prose -- doing so destroys the numbers a
    question is usually about. The table is retained here and served through
    ``query_spreadsheet``; only a generated summary is indexed for retrieval.
    """

    name: str
    header: list[str]
    rows: list[list[str]]

    @property
    def row_count(self) -> int:
        """Number of data rows, excluding the header."""
        return len(self.rows)


@dataclass(frozen=True, slots=True)
class Extracted:
    """The result of extracting one document."""

    blocks: list[Block] = field(default_factory=list)
    sheets: list[SheetTable] = field(default_factory=list)
    # Pages whose text layer was empty enough to look scanned. The OCR stage
    # reads this rather than re-deciding, so the policy lives in one place.
    ocr_pages: list[int] = field(default_factory=list)

    @property
    def text_length(self) -> int:
        """Total characters across all prose blocks."""
        return sum(len(b.text) for b in self.blocks)

    @property
    def is_empty(self) -> bool:
        """Whether extraction produced nothing usable at all."""
        return not self.blocks and not self.sheets and not self.ocr_pages


class UnsupportedFormatError(ValueError):
    """Raised when no extractor is registered for a file."""

    def __init__(self, hint: str) -> None:
        """Record the MIME type or filename that had no extractor."""
        super().__init__(f"no extractor for {hint!r}")
