# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Spreadsheet extraction.

Spreadsheets are deliberately not turned into prose blocks. Each worksheet is
kept whole as a ``SheetTable``; the retrieval layer indexes a generated summary
and serves real rows through ``query_spreadsheet``. Prose-chunking a sheet
destroys exactly the numbers a question is usually about.
"""

from __future__ import annotations

import csv
import io

import openpyxl

from go2.extraction.base import Extracted, SheetTable


def _stringify(value: object) -> str:
    """Render a cell value as text, mapping empty cells to an empty string."""
    if value is None:
        return ""
    return str(value).strip()


def _is_blank(row: list[str]) -> bool:
    return not any(cell for cell in row)


def _to_table(name: str, rows: list[list[str]]) -> SheetTable | None:
    """Build a table from raw rows, treating the first non-blank row as header."""
    populated = [r for r in rows if not _is_blank(r)]
    if not populated:
        return None
    header, *body = populated
    return SheetTable(name=name, header=header, rows=body)


def extract_xlsx(data: bytes) -> Extracted:
    """Extract every worksheet from an .xlsx file as a whole table.

    Args:
        data: Raw .xlsx bytes.

    Returns:
        One ``SheetTable`` per non-empty worksheet. No prose blocks.
    """
    # read_only keeps memory flat on large books; data_only reads the cached
    # result of a formula rather than the formula text, which is what a
    # question about a number actually wants.
    book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        sheets: list[SheetTable] = []
        for worksheet in book.worksheets:
            rows = [
                [_stringify(cell) for cell in row] for row in worksheet.iter_rows(values_only=True)
            ]
            table = _to_table(str(worksheet.title), rows)
            if table is not None:
                sheets.append(table)
        return Extracted(sheets=sheets)
    finally:
        book.close()


def extract_csv(data: bytes, name: str = "Sheet1") -> Extracted:
    """Extract a CSV file as a single table.

    Args:
        data: Raw CSV bytes, decoded as UTF-8 with replacement.
        name: Name to give the resulting sheet.

    Returns:
        A single ``SheetTable``, or an empty result if the file has no rows.
    """
    text = data.decode("utf-8", errors="replace")
    rows = [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text))]
    table = _to_table(name, rows)
    return Extracted(sheets=[table] if table is not None else [])
