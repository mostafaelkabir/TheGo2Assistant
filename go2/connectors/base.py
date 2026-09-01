# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""The contract every connector implements.

Ingestion never learns which cloud a file came from. A connector's only job is
to enumerate changes and hand back bytes in a format the extraction registry
already understands -- provider-native formats (Google Docs, Sheets, Slides)
are exported by the connector, not special-cased downstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class RemoteFile:
    """One file as the provider describes it, before any content is fetched."""

    external_id: str
    title: str
    path: str = ""
    mime: str = ""
    modified_at: datetime | None = None
    size_bytes: int | None = None
    web_url: str | None = None
    # Providers report deletions in the same change feed as edits. Carrying the
    # flag here means the sync loop has one stream to walk, not two.
    deleted: bool = False


@dataclass(frozen=True, slots=True)
class ChangeSet:
    """A page of changes plus the cursor to resume from."""

    files: list[RemoteFile] = field(default_factory=list)
    cursor: str | None = None
    has_more: bool = False


@dataclass(frozen=True, slots=True)
class FetchedContent:
    """Raw bytes plus the filename extraction should dispatch on.

    ``filename`` is not always the provider's title: exporting a Google Doc
    yields .docx bytes, and extraction dispatches on the exported form.
    """

    data: bytes
    filename: str
    mime: str


@runtime_checkable
class Connector(Protocol):
    """A source of documents."""

    source: str

    def list_changes(self, cursor: str | None) -> ChangeSet:
        """Enumerate files changed since ``cursor``.

        Args:
            cursor: Opaque provider cursor from a previous call, or ``None``
                for a full initial listing.

        Returns:
            A page of changes and the cursor to pass next.
        """
        ...

    def fetch_content(self, remote: RemoteFile) -> FetchedContent:
        """Download one file, exporting it if the provider format needs it.

        Args:
            remote: The file to fetch.

        Returns:
            Bytes plus the filename and MIME type extraction should use.
        """
        ...
