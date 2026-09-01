# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Google Drive connector.

Incremental sync uses the Drive changes feed: an opaque page token is stored
per connection and replayed, so a re-sync costs one request rather than a full
listing.

Google-native files have no downloadable bytes and must be exported. The export
targets are chosen so the existing extractors handle the result unchanged --
notably Sheets export as .xlsx rather than .csv, because the CSV export silently
returns only the first worksheet.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from go2.connectors.base import ChangeSet, FetchedContent, RemoteFile

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

SOURCE = "gdrive"

_GOOGLE_NATIVE_PREFIX = "application/vnd.google-apps."
_FOLDER_MIME = "application/vnd.google-apps.folder"

# Google-native MIME type -> (export MIME type, filename suffix).
# Sheets deliberately export as .xlsx: the text/csv export returns only the
# first worksheet, which would silently drop data.
GOOGLE_EXPORTS: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
}

FILE_FIELDS = "id,name,mimeType,modifiedTime,size,webViewLink,trashed,parents"
_LIST_FIELDS = f"nextPageToken,files({FILE_FIELDS})"
_CHANGE_FIELDS = f"nextPageToken,newStartPageToken,changes(fileId,removed,file({FILE_FIELDS}))"


class DriveService(Protocol):
    """The slice of the Drive client this connector uses.

    Narrowing it to a protocol keeps the connector testable without HTTP or
    credentials, and documents exactly what surface we depend on.

    The resource types are ``Any`` because googleapiclient builds its clients
    dynamically from a discovery document -- there is no static type to name.
    """

    def files(self) -> Any:  # noqa: ANN401 -- discovery-built resource has no static type.
        """Return the files resource."""
        ...

    def changes(self) -> Any:  # noqa: ANN401 -- discovery-built resource has no static type.
        """Return the changes resource."""
        ...


def is_exportable_folder(mime: str) -> bool:
    """Whether a MIME type is a Drive folder, which carries no content."""
    return mime == _FOLDER_MIME


def export_target(mime: str) -> tuple[str, str] | None:
    """Return the export MIME type and suffix for a Google-native file.

    Args:
        mime: The file's Drive MIME type.

    Returns:
        ``(export_mime, suffix)``, or ``None`` if the file downloads directly.
    """
    return GOOGLE_EXPORTS.get(mime)


def is_ingestable(mime: str) -> bool:
    """Whether a file is worth fetching at all.

    Folders have no content, and Google-native types we cannot export (Forms,
    Drawings, Sites) would only produce empty documents.
    """
    if is_exportable_folder(mime):
        return False
    if mime.startswith(_GOOGLE_NATIVE_PREFIX):
        return mime in GOOGLE_EXPORTS
    return True


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        logger.warning("unparseable modifiedTime %r", value)
        return None


def _parse_size(value: str | int | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_file(payload: dict[str, Any], *, deleted: bool = False) -> RemoteFile:
    """Convert a Drive ``files`` resource into a ``RemoteFile``.

    Args:
        payload: A Drive API file resource.
        deleted: Force the deleted flag, for change entries that carry no file.

    Returns:
        The provider-neutral description of the file.
    """
    return RemoteFile(
        external_id=str(payload.get("id", "")),
        title=str(payload.get("name", "")),
        mime=str(payload.get("mimeType", "")),
        modified_at=_parse_time(payload.get("modifiedTime")),
        size_bytes=_parse_size(payload.get("size")),
        web_url=payload.get("webViewLink"),
        # A trashed file is a deletion as far as the index is concerned.
        deleted=deleted or bool(payload.get("trashed")),
    )


def parse_change(entry: dict[str, Any]) -> RemoteFile:
    """Convert one entry from the Drive changes feed.

    A removed entry carries only ``fileId``; the file resource is absent, so a
    minimal deleted record is synthesised to drive removal downstream.
    """
    if entry.get("removed") or "file" not in entry:
        return RemoteFile(external_id=str(entry.get("fileId", "")), title="", deleted=True)
    return parse_file(entry["file"])


def export_filename(title: str, mime: str) -> str:
    """Filename extraction should dispatch on, after any export.

    Args:
        title: The Drive file title.
        mime: The file's Drive MIME type.

    Returns:
        The title, with an export suffix appended when the title lacks one.
    """
    target = export_target(mime)
    if target is None:
        return title
    suffix = target[1]
    return title if title.lower().endswith(suffix) else f"{title}{suffix}"


class GoogleDriveConnector:
    """Reads files and incremental changes from one Google Drive account."""

    source = SOURCE

    def __init__(self, service: DriveService, *, page_size: int = 100) -> None:
        """Wrap an authorised Drive client.

        Args:
            service: An authorised Drive v3 client, or anything satisfying
                ``DriveService``.
            page_size: Results requested per API call.
        """
        self._service = service
        self._page_size = page_size

    def start_cursor(self) -> str:
        """Fetch a fresh change-feed cursor representing 'now'."""
        response = self._service.changes().getStartPageToken().execute()
        return str(response["startPageToken"])

    def _full_listing(self) -> Iterator[RemoteFile]:
        page_token: str | None = None
        while True:
            response = (
                self._service.files()
                .list(
                    q="trashed = false",
                    spaces="drive",
                    pageSize=self._page_size,
                    pageToken=page_token,
                    fields=_LIST_FIELDS,
                )
                .execute()
            )
            for payload in response.get("files", []):
                yield parse_file(payload)
            page_token = response.get("nextPageToken")
            if not page_token:
                return

    def list_changes(self, cursor: str | None) -> ChangeSet:
        """Enumerate changed files, or everything when there is no cursor.

        Args:
            cursor: A Drive page token from a previous sync, or ``None``.

        Returns:
            Changed files and the cursor to store for next time.
        """
        if cursor is None:
            # Take the cursor before listing, so anything changed mid-listing
            # is replayed next sync rather than missed.
            next_cursor = self.start_cursor()
            files = [f for f in self._full_listing() if is_ingestable(f.mime)]
            return ChangeSet(files=files, cursor=next_cursor, has_more=False)

        response = (
            self._service.changes()
            .list(
                pageToken=cursor,
                spaces="drive",
                includeRemoved=True,
                pageSize=self._page_size,
                fields=_CHANGE_FIELDS,
            )
            .execute()
        )
        files = [parse_change(entry) for entry in response.get("changes", [])]
        # Deletions must survive the ingestable filter: a Google Form that was
        # never indexed is harmless to remove, but a deleted .pdf must be.
        files = [f for f in files if f.deleted or is_ingestable(f.mime)]

        next_page = response.get("nextPageToken")
        return ChangeSet(
            files=files,
            cursor=str(next_page or response.get("newStartPageToken") or cursor),
            has_more=bool(next_page),
        )

    def fetch_content(self, remote: RemoteFile) -> FetchedContent:
        """Download or export one file's bytes.

        Args:
            remote: The file to fetch.

        Returns:
            Bytes plus the filename and MIME type extraction should dispatch on.
        """
        target = export_target(remote.mime)
        if target is not None:
            export_mime, _ = target
            data = self._service.files().export_media(
                fileId=remote.external_id, mimeType=export_mime
            )
            return FetchedContent(
                data=_as_bytes(data),
                filename=export_filename(remote.title, remote.mime),
                mime=export_mime,
            )

        data = self._service.files().get_media(fileId=remote.external_id)
        return FetchedContent(data=_as_bytes(data), filename=remote.title, mime=remote.mime)


def _as_bytes(value: Any) -> bytes:  # noqa: ANN401 -- media response is untyped.
    """Normalise a media response, which may already be bytes or need executing."""
    if isinstance(value, bytes):
        return value
    return bytes(value.execute())
