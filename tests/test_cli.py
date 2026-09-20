# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""CLI tests.

The pure path-collection logic is tested directly; the commands that touch the
database are exercised through Typer's runner and marked slow.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from typer.testing import CliRunner

from go2.cli import _collect, app
from go2.config import Settings, get_settings
from go2.connectors.base import ChangeSet, FetchedContent, RemoteFile
from go2.jobs.worker import INGEST_FILE, run_worker
from go2.storage import repository as repo
from go2.storage.db import connect
from go2.tenancy import create_tenant, delete_tenant, resolve_tenant_id
from go2.tools.search import list_documents

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


# The unauthenticated wide bind the serve command must refuse.
ALL_INTERFACES = "0.0.0.0"  # noqa: S104 -- the bind under test, never one the test performs.


class TestServeRefusesUnauthenticatedWideBind:
    """`serve --http --host 0.0.0.0` without GO2_HTTP_TOKEN exits before binding.

    No database needed: the token check runs before the tenant lookup, so the
    exit is on the missing token and nothing else.
    """

    def test_binding_beyond_loopback_without_a_token_refuses_to_start(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GO2_HTTP_TOKEN", raising=False)
        # A stray project-local .env could set the token; make sure only the
        # environment is consulted.
        monkeypatch.setattr(Settings, "model_config", {**Settings.model_config, "env_file": None})
        get_settings.cache_clear()
        try:
            result = runner.invoke(
                app, ["serve", "--http", "--host", ALL_INTERFACES, "--port", "8799"]
            )
        finally:
            get_settings.cache_clear()
        assert result.exit_code == 1
        assert "GO2_HTTP_TOKEN" in result.output
        assert ALL_INTERFACES in result.output


@pytest.mark.slow
class TestServeValidatesTenant:
    """`serve --http` refuses to start against a tenant that does not exist.

    Needs a reachable database. Without one the command still exits 1, but on a
    connection error rather than on the tenant check -- the assertions would
    pass while testing nothing.
    """

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


@pytest.mark.slow
class TestConnectGoogle:
    """`go2 connect google`, with the real browser flow stubbed out.

    The installed-app flow itself opens a browser and talks to Google, which
    a unit test cannot do; `go2/connectors/google_auth.py` has its own tests
    for the scope, refresh and revocation logic against fakes. What this
    command adds on top -- storing the result against the *resolved* tenant --
    is what these tests cover.
    """

    @pytest.fixture
    def tenant(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
        monkeypatch.setenv("GO2_FERNET_KEY", Fernet.generate_key().decode())
        slug = f"t-{uuid.uuid4().hex[:10]}"
        monkeypatch.setenv("GO2_TENANT", slug)
        get_settings.cache_clear()
        create_tenant(slug)
        try:
            yield slug
        finally:
            delete_tenant(slug)
            get_settings.cache_clear()

    @staticmethod
    def _stub_flow(monkeypatch: pytest.MonkeyPatch, *, email: str, token: str) -> None:
        monkeypatch.setattr("go2.cli.run_installed_app_flow", lambda _path: object())
        monkeypatch.setattr("go2.cli.build_drive_service", lambda _creds: object())
        monkeypatch.setattr("go2.cli.account_email", lambda _service: email)
        monkeypatch.setattr("go2.cli.credentials_to_token", lambda _creds: token)

    def test_connect_is_tenant_scoped(self, tenant: str, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub_flow(monkeypatch, email="me@example.com", token="a-refresh-token")

        result = runner.invoke(app, ["connect", "google"])

        assert result.exit_code == 0, result.output
        assert "me@example.com" in result.output
        with connect() as conn:
            row = conn.execute(
                text("""
                    SELECT tenant_id FROM connections
                     WHERE source = 'gdrive' AND account = 'me@example.com'
                """)
            ).scalar_one()
        assert str(row) == resolve_tenant_id(tenant)

    def test_connecting_again_reauthorizes_the_same_connection(
        self, tenant: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_flow(monkeypatch, email="me@example.com", token="first-token")
        runner.invoke(app, ["connect", "google"])

        self._stub_flow(monkeypatch, email="me@example.com", token="second-token")
        result = runner.invoke(app, ["connect", "google"])

        assert result.exit_code == 0, result.output
        tenant_id = resolve_tenant_id(tenant)
        with connect() as conn:
            count = conn.execute(
                text("""
                    SELECT count(*) FROM connections
                     WHERE tenant_id = :t AND source = 'gdrive' AND account = 'me@example.com'
                """),
                {"t": tenant_id},
            ).scalar_one()
            connection_id = conn.execute(
                text("""
                    SELECT id FROM connections
                     WHERE tenant_id = :t AND source = 'gdrive' AND account = 'me@example.com'
                """),
                {"t": tenant_id},
            ).scalar_one()
            token = repo.load_token(conn, tenant_id=tenant_id, connection_id=str(connection_id))
        assert count == 1
        assert token == "second-token"


class _FakeCredentials:
    """A never-expired stand-in; refresh is google_auth's own module's to test."""

    expired = False


class _FakeSyncConnector:
    """Stands in for GoogleDriveConnector, so `sync` tests never touch Drive."""

    def __init__(
        self, files: list[RemoteFile], *, fail_titles: frozenset[str] = frozenset()
    ) -> None:
        self._files = files
        self._fail_titles = fail_titles
        self.fetched: list[str] = []

    def list_changes(self, cursor: str | None) -> ChangeSet:
        assert cursor is None  # T-012 never persists one -- see the ticket's Definition.
        return ChangeSet(files=self._files, cursor="a-cursor", has_more=False)

    def fetch_content(self, remote: RemoteFile) -> FetchedContent:
        self.fetched.append(remote.title)
        if remote.title in self._fail_titles:
            msg = f"simulated fetch failure for {remote.title}"
            raise RuntimeError(msg)
        # Mirrors GoogleDriveConnector.fetch_content: a non-exported file keeps
        # its own MIME type, which is what extraction dispatches on.
        return FetchedContent(
            data=f"This is the synced content of {remote.title}, long enough to embed.".encode(),
            filename=remote.title,
            mime=remote.mime,
        )


@pytest.mark.slow
class TestSyncCommand:
    """`go2 sync --source gdrive`, with the connector faked out.

    `tests/test_connector_contract.py` and `tests/test_gdrive.py` already
    cover the real connector's own behaviour; what this command adds on top
    -- choosing a connection, refreshing its credential, and driving files
    through the same pipeline `go2 ingest` uses -- is what these tests cover.
    """

    @pytest.fixture
    def tenant(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
        monkeypatch.setenv("GO2_FERNET_KEY", Fernet.generate_key().decode())
        slug = f"t-{uuid.uuid4().hex[:10]}"
        monkeypatch.setenv("GO2_TENANT", slug)
        get_settings.cache_clear()
        create_tenant(slug)
        tenant_id = resolve_tenant_id(slug)
        with connect() as conn:
            repo.upsert_connection_token(
                conn,
                tenant_id=tenant_id,
                source="gdrive",
                account="me@example.com",
                token="a-stored-token",
            )
        try:
            yield slug
        finally:
            delete_tenant(slug)
            get_settings.cache_clear()

    @staticmethod
    def _stub_connector(
        monkeypatch: pytest.MonkeyPatch,
        files: list[RemoteFile],
        *,
        fail_titles: frozenset[str] = frozenset(),
    ) -> _FakeSyncConnector:
        connector = _FakeSyncConnector(files, fail_titles=fail_titles)
        monkeypatch.setattr("go2.cli.credentials_from_token", lambda _token: _FakeCredentials())
        monkeypatch.setattr("go2.cli.build_drive_service", lambda _creds: object())
        monkeypatch.setattr("go2.cli.GoogleDriveConnector", lambda _service: connector)
        return connector

    @staticmethod
    def _file(title: str) -> RemoteFile:
        return RemoteFile(external_id=f"drive-{title}", title=title, mime="text/plain")

    @pytest.mark.usefixtures("tenant")
    def test_synced_files_go_through_the_same_pipeline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_connector(monkeypatch, [self._file("Contract.txt")])

        result = runner.invoke(app, ["sync"])

        assert result.exit_code == 0, result.output
        assert "Contract.txt" in result.output
        assert "indexed" in result.output
        docs = list_documents(source="gdrive")
        assert len(docs) == 1
        assert docs[0]["status"] == "indexed"

    def test_sync_is_scoped_to_the_active_tenant(
        self, tenant: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_connector(monkeypatch, [self._file("Contract.txt")])
        runner.invoke(app, ["sync"])

        tenant_id = resolve_tenant_id(tenant)
        with connect() as conn:
            row = conn.execute(
                text("SELECT tenant_id FROM documents WHERE source = 'gdrive' LIMIT 1")
            ).scalar_one()
        assert str(row) == tenant_id

    @pytest.mark.usefixtures("tenant")
    def test_limit_stops_early(self, monkeypatch: pytest.MonkeyPatch) -> None:
        connector = self._stub_connector(
            monkeypatch, [self._file("One.txt"), self._file("Two.txt"), self._file("Three.txt")]
        )

        result = runner.invoke(app, ["sync", "--limit", "1"])

        assert result.exit_code == 0, result.output
        assert connector.fetched == ["One.txt"]

    @pytest.mark.usefixtures("tenant")
    def test_an_unsupported_file_is_skipped_not_failed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        unsupported = RemoteFile(
            external_id="drive-archive", title="archive.zip", mime="application/zip"
        )
        self._stub_connector(monkeypatch, [unsupported])

        result = runner.invoke(app, ["sync"])

        assert result.exit_code == 0, result.output
        assert "skipped" in result.output
        assert "failed" not in result.output

    @pytest.mark.usefixtures("tenant")
    def test_one_bad_file_does_not_abort_the_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub_connector(
            monkeypatch,
            [self._file("1-bad.txt"), self._file("2-good.txt")],
            fail_titles=frozenset({"1-bad.txt"}),
        )

        result = runner.invoke(app, ["sync"])

        assert result.exit_code == 0, result.output
        assert "fetch failed" in result.output
        assert "2-good.txt" in result.output
        docs = list_documents(source="gdrive")
        assert len(docs) == 1
        assert docs[0]["title"] == "2-good.txt"

    @pytest.mark.usefixtures("tenant")
    def test_source_is_recorded_as_gdrive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub_connector(monkeypatch, [self._file("Contract.txt")])
        runner.invoke(app, ["sync"])

        assert len(list_documents(source="gdrive")) == 1
        assert list_documents(source="upload") == []

    def test_without_a_connection_it_names_the_fix(
        self, tenant: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tenant_id = resolve_tenant_id(tenant)
        with connect() as conn:
            conn.execute(text("DELETE FROM connections WHERE tenant_id = :t"), {"t": tenant_id})
        self._stub_connector(monkeypatch, [])

        result = runner.invoke(app, ["sync"])

        assert result.exit_code == 1
        assert "go2 connect google" in result.output
