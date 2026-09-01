# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""CLI tests.

The pure path-collection logic is tested directly; the commands that touch the
database are exercised through Typer's runner and marked slow.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from go2.cli import _collect, app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

EXPECTED_NESTED_FILES = 2


class TestCollect:
    """Turning user-supplied paths into a file list."""

    def test_a_single_file_is_returned(self, tmp_path: Path) -> None:
        target = tmp_path / "a.txt"
        target.write_text("hello")
        assert _collect([target], recursive=True) == [target]

    def test_a_directory_is_expanded(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.md").write_text("b")
        assert len(_collect([tmp_path], recursive=True)) == EXPECTED_NESTED_FILES

    def test_recursion_reaches_nested_directories(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "deeper"
        nested.mkdir(parents=True)
        (nested / "a.txt").write_text("a")
        assert len(_collect([tmp_path], recursive=True)) == 1

    def test_recursion_can_be_disabled(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep"
        nested.mkdir()
        (nested / "a.txt").write_text("a")
        assert _collect([tmp_path], recursive=False) == []

    def test_duplicates_are_collapsed(self, tmp_path: Path) -> None:
        target = tmp_path / "a.txt"
        target.write_text("a")
        # Passing a file and its parent directory must not ingest it twice.
        assert _collect([target, tmp_path], recursive=True) == [target]

    def test_a_missing_path_is_reported_not_fatal(self, tmp_path: Path) -> None:
        real = tmp_path / "a.txt"
        real.write_text("a")
        assert _collect([tmp_path / "nope.txt", real], recursive=True) == [real]


class TestCommands:
    """Command surface."""

    def test_formats_lists_supported_extensions(self) -> None:
        result = runner.invoke(app, ["formats"])
        assert result.exit_code == 0
        assert ".pdf" in result.stdout
        assert ".xlsx" in result.stdout

    def test_ingest_with_nothing_to_do_exits_nonzero(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["ingest", str(tmp_path)])
        assert result.exit_code == 1
        assert "nothing to ingest" in result.stdout


@pytest.mark.slow
class TestIngestCommand:
    """The upload path, against the real database."""

    def test_ingests_a_directory_and_reports_each_file(
        self, tmp_path: Path, pdf_with_text: bytes, xlsx_bytes: bytes
    ) -> None:
        (tmp_path / "Contract.pdf").write_bytes(pdf_with_text)
        (tmp_path / "Budget.xlsx").write_bytes(xlsx_bytes)
        (tmp_path / "archive.zip").write_bytes(b"PK\x03\x04junk")

        result = runner.invoke(app, ["ingest", str(tmp_path)])

        assert result.exit_code == 0
        assert "indexed" in result.stdout
        assert "skipped" in result.stdout
        assert "2 ingested, 1 skipped" in result.stdout
