# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""The contract every connector must satisfy, independent of provider.

`tests/test_gdrive.py` tests Google Drive's own decisions -- which MIME types
export to what, how a change resource parses. This module tests the things that
have to be true of *any* connector, and it is parameterised so that adding
OneDrive means adding one entry rather than writing a second suite.

That is the point. The architecture claims a second connector needs zero new
ingestion code; a claim like that is worth exactly what verifies it. When
OneDrive arrives, either it passes this file unchanged or the abstraction was
wrong -- and it is much cheaper to learn that on the second connector than on
the fifth.

Each case below encodes a failure that is silent rather than loud. A connector
that returns no cursor does not crash: it re-indexes the whole account on every
sync. One that drops deletions does not crash either; it leaves the index
citing documents that no longer exist.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from go2.connectors.base import ChangeSet, Connector, FetchedContent, RemoteFile
from go2.connectors.gdrive import GoogleDriveConnector
from go2.extraction.registry import find_extractor

if TYPE_CHECKING:
    from collections.abc import Callable

PDF_MIME = "application/pdf"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
FOLDER_MIME = "application/vnd.google-apps.folder"


# --------------------------------------------------------------------------
# Fakes. Deliberately local rather than imported from test_gdrive: this module
# is the specification a new connector is read against, so it should be
# readable on its own.
# --------------------------------------------------------------------------
class _Call:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.kwargs: dict[str, Any] = {}

    def __call__(self, **kwargs: Any) -> _Call:
        self.kwargs = kwargs
        return self

    def execute(self) -> Any:
        return self.result


class _Files:
    def __init__(self, listing: Any, media: bytes) -> None:
        self.list = _Call(listing)
        self.get_media = _Call(media)
        self.export_media = _Call(media)


class _Changes:
    def __init__(self, changes: Any, token: str) -> None:
        self.list = _Call(changes)
        self.getStartPageToken = _Call({"startPageToken": token})


class _Drive:
    def __init__(self, files: _Files, changes: _Changes) -> None:
        self._files, self._changes = files, changes

    def files(self) -> _Files:
        return self._files

    def changes(self) -> _Changes:
        return self._changes


def _gdrive() -> GoogleDriveConnector:
    """A Drive connector whose account holds one PDF, one sheet and a folder."""
    listing = {
        "files": [
            {
                "id": "f-pdf",
                "name": "Contract.pdf",
                "mimeType": PDF_MIME,
                "size": "2048",
                "modifiedTime": "2026-01-05T10:00:00.000Z",
            },
            {"id": "f-sheet", "name": "Budget", "mimeType": SHEET_MIME},
            {"id": "f-dir", "name": "Archive", "mimeType": FOLDER_MIME},
        ]
    }
    changes = {
        "changes": [
            {
                "fileId": "f-pdf",
                "file": {"id": "f-pdf", "name": "Contract.pdf", "mimeType": PDF_MIME},
            },
            {"fileId": "f-gone", "removed": True},
        ],
        "newStartPageToken": "TOKEN-2",
    }
    return GoogleDriveConnector(
        _Drive(_Files(listing, b"%PDF-1.4 bytes"), _Changes(changes, "TOKEN-1"))
    )


# Adding OneDrive means adding one line here, and nothing else in this file.
# Left unannotated on purpose: `pytest.param` is a function, and pytest exports
# no public type for what it returns. Reaching into `_pytest` for an annotation
# would be a worse trade than letting this one be inferred.
CONNECTORS = [pytest.param(_gdrive, id="gdrive")]


@pytest.fixture(params=CONNECTORS)
def connector(request: pytest.FixtureRequest) -> Connector:
    factory: Callable[[], Connector] = request.param
    return factory()


class TestShape:
    """A connector is recognisable as one without inheriting anything."""

    def test_satisfies_the_protocol(self, connector: Connector) -> None:
        assert isinstance(connector, Connector)

    def test_names_its_source(self, connector: Connector) -> None:
        # The source string is written into every document row, so it is part
        # of the stored data, not a display detail.
        assert isinstance(connector.source, str)
        assert connector.source.strip()
        assert connector.source == connector.source.lower()


class TestResumability:
    """Sync must be able to stop and continue without redoing the account."""

    def test_a_first_sync_returns_a_cursor(self, connector: Connector) -> None:
        # Returning None here does not fail loudly; it silently re-indexes
        # everything on every run, which looks like a slow connector.
        assert connector.list_changes(None).cursor

    def test_the_cursor_is_a_string(self, connector: Connector) -> None:
        cursor = connector.list_changes(None).cursor
        assert isinstance(cursor, str)

    def test_a_first_sync_returns_a_changeset(self, connector: Connector) -> None:
        assert isinstance(connector.list_changes(None), ChangeSet)

    def test_an_incremental_sync_also_returns_a_cursor(self, connector: Connector) -> None:
        first = connector.list_changes(None)
        assert connector.list_changes(first.cursor).cursor

    def test_has_more_is_a_bool(self, connector: Connector) -> None:
        # The sync loop branches on this; a truthy string would loop forever.
        assert isinstance(connector.list_changes(None).has_more, bool)


class TestEnumeration:
    """What comes back must be usable by ingestion without provider knowledge."""

    def test_every_file_carries_a_stable_id(self, connector: Connector) -> None:
        # external_id is the dedupe key across syncs. Empty or None means a
        # file re-ingests as a new document every time it changes.
        for f in connector.list_changes(None).files:
            assert f.external_id

    def test_every_file_carries_a_title(self, connector: Connector) -> None:
        for f in connector.list_changes(None).files:
            assert f.title

    def test_files_are_remote_file_instances(self, connector: Connector) -> None:
        assert all(isinstance(f, RemoteFile) for f in connector.list_changes(None).files)

    def test_containers_are_not_offered_as_documents(self, connector: Connector) -> None:
        # Folders have no content. Passing them through creates document rows
        # that exist only to be marked skipped.
        titles = [f.title for f in connector.list_changes(None).files]
        assert "Archive" not in titles

    def test_timestamps_are_timezone_aware(self, connector: Connector) -> None:
        # Naive datetimes compare unpredictably against stored values and make
        # "changed since" wrong in a way that is hard to see.
        for f in connector.list_changes(None).files:
            if f.modified_at is not None:
                assert f.modified_at.tzinfo is not None
                assert f.modified_at.astimezone(UTC) <= datetime.now(UTC)


class TestDeletions:
    """A deleted file must reach the sync loop, not be filtered away."""

    def test_deletions_appear_in_the_change_feed(self, connector: Connector) -> None:
        # A deletion carries no MIME type, so any "is this ingestable" filter
        # will drop it unless deletion is checked first. The symptom is an
        # index that keeps citing documents the user has removed.
        first = connector.list_changes(None)
        changed = connector.list_changes(first.cursor)
        assert any(f.deleted for f in changed.files)

    def test_a_deleted_file_still_has_an_id(self, connector: Connector) -> None:
        # Without it there is nothing to delete against.
        first = connector.list_changes(None)
        for f in connector.list_changes(first.cursor).files:
            if f.deleted:
                assert f.external_id


class TestFetching:
    """Bytes come back in a form the extraction registry already understands."""

    def test_returns_fetched_content(self, connector: Connector) -> None:
        target = next(f for f in connector.list_changes(None).files if not f.deleted)
        assert isinstance(connector.fetch_content(target), FetchedContent)

    def test_the_filename_dispatches_to_an_extractor(self, connector: Connector) -> None:
        # This is the load-bearing one. A connector may export a provider
        # format into something else entirely -- a Google Sheet arrives as
        # .xlsx -- and ingestion dispatches on the filename it is handed, not
        # on the provider's title. If that name resolves to no extractor, the
        # file is silently skipped downstream.
        for remote in connector.list_changes(None).files:
            if remote.deleted:
                continue
            fetched = connector.fetch_content(remote)
            assert find_extractor(fetched.filename, fetched.mime) is not None, (
                f"{remote.title!r} fetched as {fetched.filename!r}, which no extractor claims"
            )

    def test_content_is_bytes(self, connector: Connector) -> None:
        target = next(f for f in connector.list_changes(None).files if not f.deleted)
        assert isinstance(connector.fetch_content(target).data, bytes)

    def test_a_provider_native_file_is_converted(self, connector: Connector) -> None:
        # Google Sheets, Docs and Slides have no downloadable bytes. The
        # connector exports them; ingestion must never learn that happened.
        native = [f for f in connector.list_changes(None).files if not f.deleted]
        assert native, "fixture offers nothing to fetch"
        for remote in native:
            assert connector.fetch_content(remote).data
