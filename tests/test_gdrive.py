# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Google Drive connector tests.

Driven by a fake Drive service that returns recorded API shapes, so the change
feed, export decisions, and deletion handling are all exercised without
credentials or network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from go2.connectors.gdrive import (
    GOOGLE_EXPORTS,
    GoogleDriveConnector,
    export_filename,
    export_target,
    is_ingestable,
    parse_change,
    parse_file,
)
from go2.extraction.registry import find_extractor

DOC_MIME = "application/vnd.google-apps.document"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
SLIDES_MIME = "application/vnd.google-apps.presentation"
FORM_MIME = "application/vnd.google-apps.form"
FOLDER_MIME = "application/vnd.google-apps.folder"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

EXPECTED_SIZE = 20481


class _Call:
    """Records a call and returns a canned response."""

    def __init__(self, result: Any) -> None:
        self.result = result
        self.kwargs: dict[str, Any] = {}

    def __call__(self, **kwargs: Any) -> _Call:
        self.kwargs = kwargs
        return self

    def execute(self) -> Any:
        return self.result


class FakeFiles:
    def __init__(self, listing: Any, media: bytes = b"") -> None:
        self.list = _Call(listing)
        self.get_media = _Call(media)
        self.export_media = _Call(media)


class FakeChanges:
    def __init__(self, changes: Any, start_token: str = "TOKEN-0") -> None:
        self.list = _Call(changes)
        self.getStartPageToken = _Call({"startPageToken": start_token})


class FakeDrive:
    def __init__(self, files: FakeFiles, changes: FakeChanges) -> None:
        self._files = files
        self._changes = changes

    def files(self) -> FakeFiles:
        return self._files

    def changes(self) -> FakeChanges:
        return self._changes


class TestFormatDecisions:
    """Which files we take, and what we turn them into."""

    def test_sheets_export_as_xlsx_not_csv(self) -> None:
        # The text/csv export returns only the first worksheet, silently
        # dropping every other tab. xlsx keeps the whole workbook.
        target = export_target(SHEET_MIME)
        assert target is not None
        assert target[0] == XLSX_MIME
        assert target[1] == ".xlsx"

    def test_every_export_target_is_a_format_extraction_supports(self) -> None:
        for _, suffix in GOOGLE_EXPORTS.values():
            assert find_extractor(f"file{suffix}") is not None

    def test_binary_files_are_not_exported(self) -> None:
        assert export_target("application/pdf") is None

    def test_folders_are_skipped(self) -> None:
        assert not is_ingestable(FOLDER_MIME)

    def test_google_types_we_cannot_export_are_skipped(self) -> None:
        # A Form would otherwise be fetched and produce an empty document.
        assert not is_ingestable(FORM_MIME)

    def test_ordinary_files_are_ingestable(self) -> None:
        assert is_ingestable("application/pdf")

    @pytest.mark.parametrize("mime", [DOC_MIME, SHEET_MIME, SLIDES_MIME])
    def test_exportable_google_types_are_ingestable(self, mime: str) -> None:
        assert is_ingestable(mime)

    def test_export_filename_gains_the_suffix(self) -> None:
        assert export_filename("Q3 Budget", SHEET_MIME) == "Q3 Budget.xlsx"

    def test_export_filename_is_not_double_suffixed(self) -> None:
        assert export_filename("Q3 Budget.xlsx", SHEET_MIME) == "Q3 Budget.xlsx"


class TestParsing:
    """Drive payloads into provider-neutral records."""

    def test_parses_a_file_resource(self) -> None:
        remote = parse_file(
            {
                "id": "1abc",
                "name": "Acme Contract.pdf",
                "mimeType": "application/pdf",
                "modifiedTime": "2026-08-30T12:34:56.789Z",
                "size": "20481",
                "webViewLink": "https://drive.google.com/file/d/1abc/view",
            }
        )
        assert remote.external_id == "1abc"
        assert remote.title == "Acme Contract.pdf"
        assert remote.size_bytes == EXPECTED_SIZE
        assert remote.modified_at == datetime(2026, 8, 30, 12, 34, 56, 789000, tzinfo=UTC)
        assert not remote.deleted

    def test_a_trashed_file_counts_as_deleted(self) -> None:
        # Trashing is how most deletions actually reach us.
        assert parse_file({"id": "x", "name": "n", "trashed": True}).deleted

    def test_google_native_files_report_no_size(self) -> None:
        assert parse_file({"id": "x", "name": "Doc", "mimeType": DOC_MIME}).size_bytes is None

    def test_an_unparseable_timestamp_does_not_raise(self) -> None:
        assert (
            parse_file({"id": "x", "name": "n", "modifiedTime": "not-a-date"}).modified_at is None
        )

    def test_a_removed_change_has_no_file_resource(self) -> None:
        remote = parse_change({"fileId": "gone-1", "removed": True})
        assert remote.external_id == "gone-1"
        assert remote.deleted

    def test_a_normal_change_carries_the_file(self) -> None:
        remote = parse_change({"fileId": "1abc", "file": {"id": "1abc", "name": "Report.pdf"}})
        assert remote.title == "Report.pdf"
        assert not remote.deleted


class TestSync:
    """Cursor handling and the change feed."""

    def test_first_sync_lists_everything_and_returns_a_cursor(self) -> None:
        files = FakeFiles(
            {
                "files": [
                    {"id": "1", "name": "A.pdf", "mimeType": "application/pdf"},
                    {"id": "2", "name": "Folder", "mimeType": FOLDER_MIME},
                ]
            }
        )
        connector = GoogleDriveConnector(FakeDrive(files, FakeChanges({}, "TOKEN-1")))
        result = connector.list_changes(None)

        assert [f.title for f in result.files] == ["A.pdf"]  # folder filtered out
        assert result.cursor == "TOKEN-1"

    def test_the_cursor_is_taken_before_listing(self) -> None:
        # Taking it afterwards would lose any edit made during the listing.
        changes = FakeChanges({}, "TOKEN-1")
        files = FakeFiles({"files": []})
        GoogleDriveConnector(FakeDrive(files, changes)).list_changes(None)
        assert changes.getStartPageToken.kwargs == {}

    def test_incremental_sync_passes_the_cursor_through(self) -> None:
        changes = FakeChanges({"changes": [], "newStartPageToken": "TOKEN-9"})
        connector = GoogleDriveConnector(FakeDrive(FakeFiles({}), changes))
        result = connector.list_changes("TOKEN-5")

        assert changes.list.kwargs["pageToken"] == "TOKEN-5"
        assert changes.list.kwargs["includeRemoved"] is True
        assert result.cursor == "TOKEN-9"

    def test_deletions_survive_the_ingestable_filter(self) -> None:
        # A deleted record has no MIME type, so filtering on ingestability
        # before checking `deleted` would drop removals and orphan the index.
        changes = FakeChanges(
            {"changes": [{"fileId": "gone-1", "removed": True}], "newStartPageToken": "T2"}
        )
        result = GoogleDriveConnector(FakeDrive(FakeFiles({}), changes)).list_changes("T1")
        assert [f.external_id for f in result.files] == ["gone-1"]
        assert result.files[0].deleted

    def test_more_pages_are_reported(self) -> None:
        changes = FakeChanges({"changes": [], "nextPageToken": "TOKEN-NEXT"})
        result = GoogleDriveConnector(FakeDrive(FakeFiles({}), changes)).list_changes("T1")
        assert result.has_more
        assert result.cursor == "TOKEN-NEXT"

    def test_a_quiet_sync_reports_no_more_pages(self) -> None:
        changes = FakeChanges({"changes": [], "newStartPageToken": "T2"})
        result = GoogleDriveConnector(FakeDrive(FakeFiles({}), changes)).list_changes("T1")
        assert not result.has_more
        assert result.files == []


class TestFetch:
    """Downloading versus exporting."""

    def test_a_binary_file_is_downloaded_directly(self) -> None:
        files = FakeFiles({}, media=b"%PDF-1.7 ...")
        connector = GoogleDriveConnector(FakeDrive(files, FakeChanges({})))
        remote = parse_file({"id": "1", "name": "A.pdf", "mimeType": "application/pdf"})

        fetched = connector.fetch_content(remote)
        assert fetched.data == b"%PDF-1.7 ..."
        assert fetched.filename == "A.pdf"
        assert files.get_media.kwargs == {"fileId": "1"}

    def test_a_google_sheet_is_exported_as_xlsx(self) -> None:
        files = FakeFiles({}, media=b"PK\x03\x04")
        connector = GoogleDriveConnector(FakeDrive(files, FakeChanges({})))
        remote = parse_file({"id": "9", "name": "Q3 Budget", "mimeType": SHEET_MIME})

        fetched = connector.fetch_content(remote)
        assert files.export_media.kwargs == {"fileId": "9", "mimeType": XLSX_MIME}
        # The filename carries the exported suffix so extraction dispatches right.
        assert fetched.filename == "Q3 Budget.xlsx"
        assert fetched.mime == XLSX_MIME
