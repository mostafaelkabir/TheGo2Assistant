# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Dispatch from a file to the extractor that handles it.

Every source -- upload, Google Drive, OneDrive -- resolves through this one
table. Connectors are responsible for exporting provider-native formats
(Google Docs, Sheets, Slides) into something listed here before calling in.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import PurePosixPath

from go2.extraction.base import Block, Extracted, UnsupportedFormatError
from go2.extraction.markdown import extract_markdown
from go2.extraction.office import extract_docx, extract_pptx
from go2.extraction.pdf import extract_pdf
from go2.extraction.spreadsheet import extract_csv, extract_xlsx

Extractor = Callable[[bytes], Extracted]


def _extract_text(data: bytes) -> Extracted:
    text = data.decode("utf-8", errors="replace").strip()
    return Extracted(blocks=[Block(text=text)] if text else [])


_BY_EXTENSION: dict[str, Extractor] = {
    ".pdf": extract_pdf,
    ".docx": extract_docx,
    ".pptx": extract_pptx,
    ".xlsx": extract_xlsx,
    ".xlsm": extract_xlsx,
    ".csv": extract_csv,
    ".tsv": extract_csv,
    ".txt": _extract_text,
    ".md": extract_markdown,
    ".markdown": extract_markdown,
}

_BY_MIME: dict[str, Extractor] = {
    "application/pdf": extract_pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": extract_docx,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": extract_pptx,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": extract_xlsx,
    "text/csv": extract_csv,
    "text/plain": _extract_text,
    "text/markdown": extract_markdown,
}


def supported_extensions() -> frozenset[str]:
    """Every file extension the pipeline can currently ingest."""
    return frozenset(_BY_EXTENSION)


def find_extractor(filename: str, mime: str = "") -> Extractor | None:
    """Resolve an extractor from a filename or MIME type.

    The extension is tried first: providers frequently report a generic MIME
    type (``application/octet-stream``) for files whose name is unambiguous.

    Args:
        filename: File name or path. Only the suffix is used.
        mime: Optional MIME type, used when the extension is unknown.

    Returns:
        The matching extractor, or ``None`` if the format is unsupported.
    """
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix in _BY_EXTENSION:
        return _BY_EXTENSION[suffix]
    return _BY_MIME.get(mime.split(";", 1)[0].strip().lower())


def extract(data: bytes, filename: str, mime: str = "") -> Extracted:
    """Extract a document, dispatching on its filename or MIME type.

    Args:
        data: Raw file bytes.
        filename: File name or path, used to pick the extractor.
        mime: Optional MIME type, used when the extension is unknown.

    Returns:
        The extracted blocks and sheets.

    Raises:
        UnsupportedFormatError: If no extractor matches.
    """
    extractor = find_extractor(filename, mime)
    if extractor is None:
        raise UnsupportedFormatError(mime or filename)
    return extractor(data)


def content_hash(data: bytes) -> str:
    """Stable content hash used to key the extraction cache.

    Hashing bytes rather than provider metadata means a file that is renamed,
    moved, or re-synced unchanged is never re-extracted -- which matters most
    for OCR, the only meaningful per-file cost.

    Args:
        data: Raw file bytes.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    return hashlib.sha256(data).hexdigest()
