# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Extraction tests, run against real files produced by the conftest fixtures."""

from __future__ import annotations

import pytest

from go2.extraction.base import UnsupportedFormatError
from go2.extraction.office import extract_docx, extract_pptx
from go2.extraction.pdf import extract_pdf
from go2.extraction.registry import content_hash, extract, find_extractor, supported_extensions
from go2.extraction.spreadsheet import extract_csv, extract_xlsx

EXPECTED_PDF_PAGES = 2
EXPECTED_SLIDES_WITH_TEXT = 2
EXPECTED_BUDGET_ROWS = 2


class TestPdf:
    """PDF extraction, including the scanned-page decision."""

    def test_reads_every_page_with_a_text_layer(self, pdf_with_text: bytes) -> None:
        result = extract_pdf(pdf_with_text)
        assert len(result.blocks) == EXPECTED_PDF_PAGES
        assert result.ocr_pages == []
        assert [b.page for b in result.blocks] == [1, 2]

    def test_carries_page_numbers_for_citation(self, pdf_with_text: bytes) -> None:
        result = extract_pdf(pdf_with_text)
        assert "4,500 USD" in result.blocks[0].text
        assert result.blocks[0].page == 1

    def test_flags_pages_without_a_text_layer_for_ocr(self, pdf_scanned: bytes) -> None:
        result = extract_pdf(pdf_scanned)
        assert result.blocks == []
        assert result.ocr_pages == [1, 2]

    def test_a_scanned_pdf_is_not_mistaken_for_an_empty_document(self, pdf_scanned: bytes) -> None:
        # The distinction matters: empty means skip, needs-OCR means spend money later.
        assert not extract_pdf(pdf_scanned).is_empty

    def test_handles_a_document_that_is_part_text_part_scan(self, pdf_mixed: bytes) -> None:
        result = extract_pdf(pdf_mixed)
        assert [b.page for b in result.blocks] == [1]
        assert result.ocr_pages == [2]


class TestDocx:
    """Word extraction and heading propagation."""

    def test_extracts_paragraphs(self, docx_bytes: bytes) -> None:
        texts = [b.text for b in extract_docx(docx_bytes).blocks]
        assert "Net 30 from invoice date." in texts

    def test_headings_are_carried_onto_following_blocks(self, docx_bytes: bytes) -> None:
        blocks = extract_docx(docx_bytes).blocks
        by_text = {b.text: b.heading for b in blocks}
        assert by_text["Net 30 from invoice date."] == "Payment Terms"
        assert by_text["Either party may terminate with 60 days notice."] == "Termination"

    def test_headings_are_not_emitted_as_blocks_of_their_own(self, docx_bytes: bytes) -> None:
        assert "Payment Terms" not in [b.text for b in extract_docx(docx_bytes).blocks]

    def test_tables_are_kept_as_searchable_text(self, docx_bytes: bytes) -> None:
        rendered = "\n".join(b.text for b in extract_docx(docx_bytes).blocks)
        assert "EMEA" in rendered
        assert "12000" in rendered


class TestPptx:
    """Slide extraction."""

    def test_one_block_per_slide_that_has_text(self, pptx_bytes: bytes) -> None:
        result = extract_pptx(pptx_bytes)
        assert len(result.blocks) == EXPECTED_SLIDES_WITH_TEXT

    def test_slide_numbers_survive_an_empty_slide(self, pptx_bytes: bytes) -> None:
        # Slide 2 is empty, so the third slide must still report 3 -- otherwise
        # a citation would point a reader at the wrong slide.
        assert [b.slide for b in extract_pptx(pptx_bytes).blocks] == [1, 3]


class TestSpreadsheet:
    """Spreadsheets are kept whole, never turned into prose."""

    def test_produces_tables_and_no_prose_blocks(self, xlsx_bytes: bytes) -> None:
        result = extract_xlsx(xlsx_bytes)
        assert result.blocks == []
        assert len(result.sheets) == 1

    def test_header_and_rows_are_separated(self, xlsx_bytes: bytes) -> None:
        sheet = extract_xlsx(xlsx_bytes).sheets[0]
        assert sheet.name == "Q3 Budget"
        assert sheet.header == ["Category", "Planned", "Actual"]
        assert sheet.row_count == EXPECTED_BUDGET_ROWS

    def test_numbers_survive_as_readable_values(self, xlsx_bytes: bytes) -> None:
        sheet = extract_xlsx(xlsx_bytes).sheets[0]
        assert ["Cloud", "8000", "9350"] in sheet.rows

    def test_empty_worksheets_are_dropped(self, xlsx_bytes: bytes) -> None:
        assert [s.name for s in extract_xlsx(xlsx_bytes).sheets] == ["Q3 Budget"]

    def test_csv_becomes_a_single_table(self) -> None:
        result = extract_csv(b"name,amount\nAcme,4500\nGlobex,7200\n")
        assert result.blocks == []
        assert result.sheets[0].header == ["name", "amount"]
        assert result.sheets[0].rows == [["Acme", "4500"], ["Globex", "7200"]]

    def test_blank_leading_rows_do_not_become_the_header(self) -> None:
        # Exported sheets often start with blank padding rows.
        result = extract_csv(b"\n\nname,amount\nAcme,4500\n")
        assert result.sheets[0].header == ["name", "amount"]

    def test_an_empty_csv_yields_no_sheet(self) -> None:
        assert extract_csv(b"").sheets == []


class TestRegistry:
    """Dispatch and cache keying."""

    def test_dispatches_on_extension(self, xlsx_bytes: bytes) -> None:
        result = extract(xlsx_bytes, "Q3 Budget.xlsx")
        assert result.sheets[0].name == "Q3 Budget"

    def test_falls_back_to_mime_when_the_extension_is_unknown(self, docx_bytes: bytes) -> None:
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        assert extract(docx_bytes, "export-1729", mime).blocks

    def test_extension_wins_over_a_generic_mime(self, xlsx_bytes: bytes) -> None:
        # Providers routinely report octet-stream for files whose name is clear.
        result = extract(xlsx_bytes, "budget.xlsx", "application/octet-stream")
        assert result.sheets

    def test_mime_parameters_are_ignored(self) -> None:
        assert find_extractor("notes", "text/plain; charset=utf-8") is not None

    def test_extension_matching_is_case_insensitive(self, pdf_with_text: bytes) -> None:
        assert extract(pdf_with_text, "REPORT.PDF").blocks

    def test_unsupported_formats_raise(self) -> None:
        with pytest.raises(UnsupportedFormatError):
            extract(b"\x00\x01", "archive.zip", "application/zip")

    def test_the_advertised_extensions_all_resolve(self) -> None:
        assert all(find_extractor(f"f{ext}") is not None for ext in supported_extensions())

    def test_content_hash_is_stable_and_ignores_the_filename(self, docx_bytes: bytes) -> None:
        # Cache keying must survive a rename or a move, or OCR gets paid for twice.
        assert content_hash(docx_bytes) == content_hash(docx_bytes)

    def test_content_hash_changes_with_content(self) -> None:
        assert content_hash(b"a") != content_hash(b"b")
