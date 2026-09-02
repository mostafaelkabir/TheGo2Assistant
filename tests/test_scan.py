# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Pre-ingest scanning, and the two ways it could lie.

A scan exists to tell you what is in material you have not yet cleared. The
failure that matters is not a missed pattern but a confident "clean" over
something nobody read -- a spreadsheet whose cells were never looked at, or a
file that could not be opened at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from go2.security.scan import scan_files

if TYPE_CHECKING:
    from pathlib import Path

# Luhn-valid test card, leading 4 so it passes the ISO 7812 issuer check.
CARD = "4111111111111111"


class TestSpreadsheets:
    """Cells are scanned, not just prose."""

    def test_a_csv_with_a_card_is_not_reported_clean(self, tmp_path: Path) -> None:
        # Spreadsheets deliberately produce no prose blocks, so reading blocks
        # alone built an empty body and pronounced every sheet clean.
        path = tmp_path / "payments.csv"
        path.write_text(f"name,card\nAcme,{CARD}\n")
        report = scan_files([path])
        assert report.files, "a card in a spreadsheet cell went unreported"
        assert report.totals.get("credit_card") == 1

    def test_emails_in_cells_are_found(self, tmp_path: Path) -> None:
        path = tmp_path / "contacts.csv"
        path.write_text("name,email\nAcme,ops@acme.example\n")
        assert scan_files([path]).totals.get("email") == 1

    def test_the_header_row_is_scanned_too(self, tmp_path: Path) -> None:
        path = tmp_path / "odd.csv"
        path.write_text("ops@acme.example,amount\nAcme,10\n")
        assert scan_files([path]).totals.get("email") == 1

    def test_a_clean_spreadsheet_is_still_clean(self, tmp_path: Path) -> None:
        path = tmp_path / "budget.csv"
        path.write_text("category,planned\nCloud,8000\n")
        assert scan_files([path]).files == []

    def test_a_scanned_spreadsheet_counts_as_scanned(self, tmp_path: Path) -> None:
        path = tmp_path / "budget.csv"
        path.write_text("category,planned\nCloud,8000\n")
        assert scan_files([path]).scanned == 1


class TestBlindSpots:
    """A file that was not read is reported as not read."""

    def test_an_unreadable_file_is_counted(self, tmp_path: Path) -> None:
        path = tmp_path / "secret.csv"
        path.write_text("name,email\nAcme,ops@acme.example\n")
        path.chmod(0o000)
        try:
            report = scan_files([path])
        finally:
            path.chmod(0o600)
        assert report.unreadable == 1, "an unreadable file was silently dropped"
        assert report.scanned == 0

    def test_an_unreadable_file_is_not_reported_as_clean(self, tmp_path: Path) -> None:
        path = tmp_path / "secret.csv"
        path.write_text(f"name,card\nAcme,{CARD}\n")
        path.chmod(0o000)
        try:
            report = scan_files([path])
        finally:
            path.chmod(0o600)
        assert report.files == []
        assert report.unreadable == 1

    def test_a_missing_file_is_counted_rather_than_ignored(self, tmp_path: Path) -> None:
        assert scan_files([tmp_path / "gone.csv"]).unreadable == 1

    def test_an_unsupported_format_is_skipped_without_inflating_the_scan(
        self, tmp_path: Path
    ) -> None:
        # Not a blind spot: there was nothing to extract, and counting it as
        # scanned would overstate what the report covered.
        path = tmp_path / "archive.zip"
        path.write_bytes(b"PK\x03\x04")
        report = scan_files([path])
        assert report.scanned == 0
        assert report.unreadable == 0
