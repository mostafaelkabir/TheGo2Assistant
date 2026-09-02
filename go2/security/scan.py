# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Scanning files for sensitive values without ingesting them.

Separate from the CLI so the same check can run from a connector before a sync,
or from a test, rather than only when a person types a command.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from go2.extraction.base import Extracted, UnsupportedFormatError
from go2.extraction.registry import extract
from go2.security.pii import Finding, detect, summarise

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FileReport:
    """What one file contains."""

    path: Path
    findings: list[Finding]
    body: str

    @property
    def counts(self) -> dict[str, int]:
        """Findings by category."""
        return summarise(self.findings)


@dataclass(frozen=True, slots=True)
class ScanReport:
    """The result of scanning a set of files."""

    scanned: int = 0
    unreadable: int = 0
    files: list[FileReport] = field(default_factory=list)

    @property
    def totals(self) -> dict[str, int]:
        """Findings by category across every file."""
        out: dict[str, int] = {}
        for report in self.files:
            for kind, number in report.counts.items():
                out[kind] = out.get(kind, 0) + number
        return out


def _scannable_text(extracted: Extracted) -> str:
    """Every piece of text in an extraction, prose and cells alike.

    Spreadsheets deliberately produce no prose blocks -- the table is kept
    whole rather than chunked -- so reading ``blocks`` alone builds an empty
    body and pronounces every spreadsheet clean. Cells are exactly where card
    numbers, emails and phone numbers sit in the files people actually export.
    """
    parts = [b.text for b in extracted.blocks]
    for sheet in extracted.sheets:
        parts.append(sheet.name)
        parts.append(" ".join(sheet.header))
        parts.extend(" ".join(row) for row in sheet.rows)
    return "\n".join(parts)


def scan_files(paths: Sequence[Path]) -> ScanReport:
    """Extract each file locally and report sensitive values found.

    Nothing is sent anywhere and nothing is written to the index, so this is
    safe to run against material that has not been cleared for ingestion.

    Args:
        paths: Files to scan.

    Returns:
        Per-file findings plus a count of files that could not be read --
        a scan that hides its own blind spots is worse than no scan.
    """
    reports: list[FileReport] = []
    scanned = unreadable = 0

    for path in paths:
        try:
            extracted = extract(path.read_bytes(), path.name)
        except UnsupportedFormatError:
            continue
        except OSError as exc:
            # A file that exists but cannot be read was not inspected. Skipping
            # it silently would report a clean scan over material nobody looked
            # at, which is the one thing this report promises not to do.
            logger.warning("could not read %s: %s", path.name, exc)
            unreadable += 1
            continue
        except Exception as exc:  # noqa: BLE001 -- one bad file must not stop the scan.
            logger.warning("could not scan %s: %s", path.name, exc)
            unreadable += 1
            continue

        scanned += 1
        body = _scannable_text(extracted)
        findings = detect(body)
        if findings:
            reports.append(FileReport(path=path, findings=findings, body=body))

    return ScanReport(scanned=scanned, unreadable=unreadable, files=reports)
