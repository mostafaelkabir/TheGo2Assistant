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
from go2.config import Settings, get_settings
from go2.jobs.worker import INGEST_FILE, run_worker
from go2.storage import repository as repo
from go2.storage.db import connect
from go2.tenancy import resolve_tenant_id

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
def _clean_uploads(tmp_path: Path) -> Iterator[None]:
    """Remove only the rows this test committed.

    The other database tests roll back, but the CLI opens its own connections
    and commits them, so its residue has to be cleared explicitly.

    Scoped to this test's tmp_path rather than to `source = 'upload'`. The
    broad delete also destroys a developer's real locally-ingested corpus --
    running the suite would silently wipe the index they were testing against.
    """
    yield
    with connect() as conn:
        conn.execute(
            text("DELETE FROM documents WHERE source = :s AND path LIKE :prefix"),
            {"s": "upload", "prefix": f"{tmp_path}%"},
        )


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


@pytest.mark.slow
class TestQueue:
    """Background ingestion: enqueue, claim, drain.

    `run_worker` drains every queued job for the tenant, so these tests skip
    when a real backlog is present rather than consuming someone's queue.
    """

    @pytest.fixture(autouse=True)
    def _require_empty_queue(self) -> None:
        with connect() as conn:
            queued = repo.job_counts(conn, tenant_id=resolve_tenant_id()).get("queued", 0)
        if queued:
            pytest.skip(f"{queued} jobs already queued; not draining a real backlog")

    @pytest.fixture
    def _clean_queue(self, tmp_path: Path) -> Iterator[None]:
        """Remove only the jobs this test queued.

        Scoped by payload path for the same reason the document cleanup is
        scoped by tmp_path: a blanket delete would wipe a real queued backlog
        that someone left running.
        """
        yield
        with connect() as conn:
            conn.execute(
                text("DELETE FROM jobs WHERE kind = :k AND payload->>'path' LIKE :prefix"),
                {"k": INGEST_FILE, "prefix": f"{tmp_path}%"},
            )

    @pytest.mark.usefixtures("_clean_queue", "_clean_uploads")
    def test_background_queues_without_ingesting(
        self, tmp_path: Path, pdf_with_text: bytes
    ) -> None:
        (tmp_path / "a.pdf").write_bytes(pdf_with_text)
        (tmp_path / "b.pdf").write_bytes(pdf_with_text)

        result = runner.invoke(app, ["ingest", str(tmp_path), "--background"])

        assert result.exit_code == 0
        assert "queued 2 files" in result.stdout
        with connect() as conn:
            assert (
                repo.job_counts(conn, tenant_id=resolve_tenant_id()).get("queued", 0)
                >= EXPECTED_NESTED_FILES
            )

    @pytest.mark.usefixtures("_clean_queue", "_clean_uploads")
    def test_the_worker_drains_the_queue(self, tmp_path: Path, pdf_with_text: bytes) -> None:
        (tmp_path / "a.pdf").write_bytes(pdf_with_text)
        runner.invoke(app, ["ingest", str(tmp_path), "--background"])

        report = run_worker(tenant_id=resolve_tenant_id(), once=True)

        assert report.processed >= 1
        assert report.chunks > 0
        with connect() as conn:
            assert repo.job_counts(conn, tenant_id=resolve_tenant_id()).get("queued", 0) == 0

    @pytest.mark.usefixtures("_clean_queue", "_clean_uploads")
    def test_an_oversized_file_is_skipped_not_embedded(self, tmp_path: Path) -> None:
        # The whole reason the cap exists: one huge file must not silently
        # consume the queue for hours.
        big = tmp_path / "huge.md"
        big.write_text("# Heading\n" + ("word " * 200_000))
        runner.invoke(app, ["ingest", str(tmp_path), "--background"])

        report = run_worker(tenant_id=resolve_tenant_id(), once=True, max_bytes=1000)

        assert report.processed == 1
        assert report.chunks == 0  # skipped, not embedded
        assert report.failed == 0  # and not counted as an error

    @pytest.mark.usefixtures("_clean_queue", "_clean_uploads")
    def test_a_missing_file_fails_that_job_only(self, tmp_path: Path, pdf_with_text: bytes) -> None:
        good = tmp_path / "a.pdf"
        good.write_bytes(pdf_with_text)
        gone = tmp_path / "b.pdf"
        gone.write_bytes(pdf_with_text)
        runner.invoke(app, ["ingest", str(tmp_path), "--background"])
        gone.unlink()  # deleted between queueing and processing

        report = run_worker(tenant_id=resolve_tenant_id(), once=True)

        assert report.failed == 1
        assert report.processed == 1  # the other file still went through

    @pytest.mark.usefixtures("_clean_queue")
    def test_a_claimed_job_is_not_handed_out_twice(self, tmp_path: Path) -> None:
        # FOR UPDATE SKIP LOCKED is what makes concurrent workers safe.
        tenant_id = resolve_tenant_id()
        with connect() as conn:
            repo.enqueue_job(
                conn, tenant_id=tenant_id, kind=INGEST_FILE, payload={"path": str(tmp_path)}
            )
        with connect() as conn:
            first = repo.claim_job(conn, tenant_id=tenant_id, kind=INGEST_FILE)
        with connect() as conn:
            second = repo.claim_job(conn, tenant_id=tenant_id, kind=INGEST_FILE)

        assert first is not None
        assert second is None

    @pytest.mark.usefixtures("_clean_queue")
    def test_jobs_reports_the_queue(self, tmp_path: Path) -> None:
        with connect() as conn:
            repo.enqueue_job(
                conn,
                tenant_id=resolve_tenant_id(),
                kind=INGEST_FILE,
                payload={"path": str(tmp_path / "x")},
            )
        assert "queued" in runner.invoke(app, ["jobs"]).stdout


class TestConfigLocation:
    """Config must not depend on where the command was typed."""

    @staticmethod
    def _env_sources() -> list[str]:
        sources = Settings.model_config["env_file"]
        assert isinstance(sources, tuple)
        return [str(p) for p in sources]

    def test_a_user_level_env_file_is_read(self) -> None:
        # `go2` runs from any directory, but a bare ".env" resolves against the
        # current one. Searching from another folder silently used defaults and
        # returned nothing, because the configured provider was never read.
        assert any("config" in p and "go2" in p for p in self._env_sources())

    def test_a_project_env_file_still_wins(self) -> None:
        # Later entries override earlier ones in pydantic-settings, so a
        # project-local file must come last.
        assert self._env_sources()[-1] == ".env"


class TestServeValidatesTenant:
    """`serve --http` refuses to start against a tenant that does not exist."""

    def test_an_unknown_tenant_exits_rather_than_serving(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Without this the server binds happily, the client discovers three
        # tools, and every question fails instead of the process failing once.
        monkeypatch.setenv("GO2_TENANT", "definitely-not-a-tenant")
        get_settings.cache_clear()
        try:
            result = runner.invoke(app, ["serve", "--http", "--port", "8799"])
        finally:
            get_settings.cache_clear()
        assert result.exit_code == 1

    def test_the_failure_names_the_fix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GO2_TENANT", "definitely-not-a-tenant")
        get_settings.cache_clear()
        try:
            result = runner.invoke(app, ["serve", "--http", "--port", "8799"])
        finally:
            get_settings.cache_clear()
        assert "go2 tenant create" in result.output
