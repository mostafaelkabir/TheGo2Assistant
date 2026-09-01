# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""CLI tests.

The pure path-collection logic is tested directly; the commands that touch the
database are exercised through Typer's runner and marked slow.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from go2.cli import _collect, app
from go2.storage.db import connect

if TYPE_CHECKING:
    from collections.abc import Iterator
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

    def test_unsupported_formats_are_not_collected_from_a_directory(self, tmp_path: Path) -> None:
        # Scanning a source tree must not create a document row per .py file
        # just to mark it skipped.
        (tmp_path / "notes.md").write_text("keep")
        (tmp_path / "main.py").write_text("drop")
        (tmp_path / "run.log").write_text("drop")
        assert [p.name for p in _collect([tmp_path], recursive=True)] == ["notes.md"]

    def test_all_files_overrides_the_format_filter(self, tmp_path: Path) -> None:
        (tmp_path / "notes.md").write_text("keep")
        (tmp_path / "main.py").write_text("keep too")
        found = _collect([tmp_path], recursive=True, all_files=True)
        assert {p.name for p in found} == {"notes.md", "main.py"}

    def test_a_file_named_explicitly_is_always_kept(self, tmp_path: Path) -> None:
        # Naming a file is an explicit instruction; only directory scans filter.
        odd = tmp_path / "data.weird"
        odd.write_text("x")
        assert _collect([odd], recursive=True) == [odd]

    def test_hidden_files_are_never_collected(self, tmp_path: Path) -> None:
        # A dotfile is where secrets live. Indexing a project folder must not
        # sweep up a .env, and pathlib's glob includes dotfiles by default.
        (tmp_path / ".env").write_text("SECRET=value")
        (tmp_path / "notes.md").write_text("keep")
        assert [p.name for p in _collect([tmp_path], recursive=True)] == ["notes.md"]

    def test_hidden_directories_are_not_walked(self, tmp_path: Path) -> None:
        git = tmp_path / ".git"
        git.mkdir()
        (git / "COMMIT_EDITMSG.md").write_text("drop")
        (tmp_path / "notes.md").write_text("keep")
        assert [p.name for p in _collect([tmp_path], recursive=True)] == ["notes.md"]

    @pytest.mark.parametrize("junk", ["node_modules", "__pycache__", "venv", "dist"])
    def test_build_directories_are_skipped(self, tmp_path: Path, junk: str) -> None:
        noisy = tmp_path / junk
        noisy.mkdir()
        (noisy / "README.md").write_text("drop")
        (tmp_path / "notes.md").write_text("keep")
        assert [p.name for p in _collect([tmp_path], recursive=True)] == ["notes.md"]

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


@pytest.fixture
def _clean_uploads() -> Iterator[None]:
    """Remove rows the CLI committed.

    The other database tests roll back, but the CLI opens its own connections
    and commits them, so its residue has to be cleared explicitly or it
    accumulates in the developer's database run after run.
    """
    yield
    with connect() as conn:
        conn.execute(text("DELETE FROM documents WHERE source = :s"), {"s": "upload"})
        conn.execute(text("DELETE FROM connections WHERE source = :s"), {"s": "upload"})


@pytest.mark.slow
@pytest.mark.usefixtures("_clean_uploads")
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
        assert "Contract.pdf" in result.stdout
        assert "Budget.xlsx" in result.stdout
        # The .zip is filtered at collection, so it never becomes a document
        # row. Scanning a directory should not record what it cannot read.
        assert "archive.zip" not in result.stdout
        assert "2 indexed" in result.stdout

    def test_all_surfaces_unreadable_files_as_skipped(
        self, tmp_path: Path, pdf_with_text: bytes
    ) -> None:
        (tmp_path / "Contract.pdf").write_bytes(pdf_with_text)
        (tmp_path / "archive.zip").write_bytes(b"PK\x03\x04junk")

        result = runner.invoke(app, ["ingest", str(tmp_path), "--all"])

        assert "archive.zip" in result.stdout
        assert "1 skipped" in result.stdout

    def test_a_corrupt_file_does_not_abort_the_batch(
        self, tmp_path: Path, pdf_with_text: bytes
    ) -> None:
        # Files are processed in sorted order, so the corrupt one sits between
        # two good ones: if it aborted the loop, the third would never index.
        (tmp_path / "1-good.pdf").write_bytes(pdf_with_text)
        (tmp_path / "2-corrupt.pdf").write_bytes(b"%PDF-1.7\n" + b"\xde\xad\xbe\xef" * 200)
        (tmp_path / "3-good.pdf").write_bytes(pdf_with_text)

        result = runner.invoke(app, ["ingest", str(tmp_path)])

        assert result.exit_code == 0
        assert "failed" in result.stdout
        assert "3-good.pdf" in result.stdout
        assert "2 indexed" in result.stdout

    def test_a_second_run_over_unchanged_files_does_no_work(
        self, tmp_path: Path, pdf_with_text: bytes
    ) -> None:
        (tmp_path / "Contract.pdf").write_bytes(pdf_with_text)
        runner.invoke(app, ["ingest", str(tmp_path)])

        result = runner.invoke(app, ["ingest", str(tmp_path)])
        assert "unchanged" in result.stdout
