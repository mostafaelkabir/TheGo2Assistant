# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Command line entry point."""

from __future__ import annotations

import logging
import time
from collections import Counter
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import text

from go2.connectors.base import FetchedContent, RemoteFile
from go2.extraction.registry import supported_extensions
from go2.jobs.ingest import IngestResult, ingest_document
from go2.jobs.worker import DEFAULT_MAX_BYTES, enqueue_paths, run_worker
from go2.rag.retrieval import SearchFilters, SearchOptions
from go2.rag.retrieval import search as run_search
from go2.scope import Scope
from go2.storage import repository as repo
from go2.storage.db import connect, default_tenant_id
from go2.storage.db import migrate as run_migrations

app = typer.Typer(help="Ask your assistant about your OneDrive and Google Drive files.")

UPLOAD_SOURCE = "upload"


@app.callback()
def _configure(
    *, verbose: bool = typer.Option(default=False, help="Enable debug logging.")
) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )


@app.command()
def migrate() -> None:
    """Apply pending database migrations."""
    applied = run_migrations()
    typer.echo(f"applied: {', '.join(applied)}" if applied else "already up to date")


@app.command()
def formats() -> None:
    """List the file formats that can be ingested."""
    typer.echo(" ".join(sorted(supported_extensions())))


@app.command()
def ingest(
    paths: Annotated[list[Path], typer.Argument(help="Files or directories to ingest.")],
    *,
    recursive: bool = typer.Option(default=True, help="Descend into directories."),
    all_files: Annotated[
        bool, typer.Option("--all", help="Include every file, not just supported formats.")
    ] = False,
    background: Annotated[
        bool, typer.Option("--background", help="Queue the work and exit; run `go2 worker`.")
    ] = False,
    max_size: Annotated[
        int, typer.Option(help="Skip files larger than this many bytes.")
    ] = DEFAULT_MAX_BYTES,
) -> None:
    """Ingest local files through the same pipeline the connectors use.

    This is the upload path. It shares extraction, chunking, and embedding with
    Google Drive and OneDrive -- there is no separate ingestion route.

    Scanning a directory keeps only readable formats and skips hidden entries
    and build directories. Run `go2 formats` to see what is supported.
    """
    files = _collect(paths, recursive=recursive, all_files=all_files)
    if not files:
        typer.echo("nothing to ingest")
        raise typer.Exit(code=1)

    tenant_id = default_tenant_id()

    if background:
        queued = enqueue_paths(files, tenant_id=tenant_id, source=UPLOAD_SOURCE, account="local")
        typer.echo(f"queued {queued} files\nrun `go2 worker` to process them")
        return

    oversized = [p for p in files if p.stat().st_size > max_size]
    for path in oversized:
        typer.echo(f"{'too-large':9} {path.name}  ({path.stat().st_size / 1_000_000:.1f} MB)")
    files = [p for p in files if p.stat().st_size <= max_size]

    tally: Counter[str] = Counter()
    tally["too-large"] = len(oversized)
    total = len(files)
    started = time.monotonic()

    for index, path in enumerate(files, start=1):
        # Each file gets its own transaction and its own error boundary, so one
        # unreadable or corrupt file cannot abort the rest of the batch.
        try:
            data = path.read_bytes()
        except OSError as exc:
            typer.echo(f"{'failed':9} {path.name}  (unreadable: {exc.strerror or exc})")
            tally["failed"] += 1
            continue

        with connect() as conn:
            scope = Scope(
                tenant_id=tenant_id,
                connection_id=repo.ensure_connection(
                    conn, tenant_id=tenant_id, source=UPLOAD_SOURCE, account="local"
                ),
                source=UPLOAD_SOURCE,
            )
            result = ingest_document(
                conn,
                scope=scope,
                remote=RemoteFile(
                    external_id=str(path.resolve()),
                    title=path.name,
                    path=str(path.parent),
                    size_bytes=len(data),
                ),
                content=FetchedContent(data=data, filename=path.name, mime=""),
            )

        typer.echo(
            f"[{index:>{len(str(total))}}/{total}] {result.status:9} {path.name}"
            f"  ({_describe(result)}){_eta(started, index, total)}"
        )
        tally["unchanged" if result.unchanged else result.status] += 1

    summary = ", ".join(f"{count} {name}" for name, count in sorted(tally.items()) if count)
    typer.echo(f"\n{summary} in {time.monotonic() - started:.0f}s")


def _eta(started: float, done: int, total: int) -> str:
    """A trailing estimate, shown only once there is enough data to mean anything."""
    if done < 2 or done >= total:  # noqa: PLR2004 -- one sample is not a rate.
        return ""
    remaining = (time.monotonic() - started) / done * (total - done)
    return f"  ~{remaining / 60:.0f}m left" if remaining > 90 else f"  ~{remaining:.0f}s left"  # noqa: PLR2004 -- seconds vs minutes threshold.


def _describe(result: IngestResult) -> str:
    """One-line detail for a finished document."""
    if result.unchanged:
        return f"unchanged, {result.chunks} chunks retained"
    if result.reason and result.status in {"skipped", "failed"}:
        return result.reason
    detail = f"{result.chunks} chunks"
    if result.sheets:
        detail += f", {result.sheets} sheets"
    if result.ocr_pages:
        detail += f", {result.ocr_pages} pages awaiting OCR"
    return detail


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="A natural-language question.")],
    *,
    limit: int = typer.Option(default=5, help="How many passages to show."),
    source: str = typer.Option(default="", help="Restrict to one connector."),
    no_rerank: bool = typer.Option(default=False, help="Skip the cross-encoder."),
) -> None:
    """Search indexed documents from the terminal.

    The same retrieval the MCP server exposes, for checking quality without a
    client attached.
    """
    tenant_id = default_tenant_id()
    with connect() as conn:
        hits = run_search(
            conn,
            tenant_id=tenant_id,
            query=query,
            filters=SearchFilters(source=source or None),
            options=SearchOptions(limit=limit, rerank=not no_rerank),
        )

    if not hits:
        typer.echo("no matches")
        return

    for rank, hit in enumerate(hits, start=1):
        snippet = " ".join(hit.text.split())[:220]
        typer.echo(f"\n{rank}. {hit.citation()}   [{hit.score:.3f}]")
        typer.echo(f"   {snippet}...")


@app.command()
def serve() -> None:
    """Run the MCP server on stdio for Claude Code or Claude Desktop."""
    from go2.mcp_server import main as run_server  # noqa: PLC0415 -- defer the mcp import.

    run_server()


@app.command()
def worker(
    *,
    once: Annotated[
        bool, typer.Option("--once", help="Exit when the queue empties instead of polling.")
    ] = False,
    max_size: Annotated[
        int, typer.Option(help="Skip files larger than this many bytes.")
    ] = DEFAULT_MAX_BYTES,
) -> None:
    """Process queued ingestion work.

    Embedding is slow enough on CPU that a large folder is better handed to a
    worker than watched in a terminal. Safe to run more than one.
    """
    tenant_id = default_tenant_id()
    started = time.monotonic()

    def progress(name: str, chunks: int, remaining: int) -> None:
        typer.echo(f"{chunks:>4} chunks  {name}   ({remaining} left)")

    typer.echo("worker running — ctrl-c to stop" if not once else "draining queue…")
    try:
        report = run_worker(
            tenant_id=tenant_id, max_bytes=max_size, once=once, on_progress=progress
        )
    except KeyboardInterrupt:
        typer.echo(f"\nstopped after {time.monotonic() - started:.0f}s")
        return

    typer.echo(
        f"\n{report.processed} files, {report.chunks} chunks, {report.failed} failed "
        f"in {report.seconds:.0f}s ({report.rate:.1f} files/min)"
    )


@app.command()
def jobs(
    *, clear: Annotated[bool, typer.Option("--clear", help="Delete finished jobs.")] = False
) -> None:
    """Show the ingestion queue."""
    tenant_id = default_tenant_id()
    with connect() as conn:
        if clear:
            removed = repo.clear_finished_jobs(conn, tenant_id=tenant_id)
            typer.echo(f"removed {removed} finished jobs")
            return
        counts = repo.job_counts(conn, tenant_id=tenant_id)

    if not counts:
        typer.echo("queue is empty")
        return
    for state in ("queued", "running", "done", "failed"):
        if counts.get(state):
            typer.echo(f"{state:9} {counts[state]:>6}")


@app.command()
def status() -> None:
    """Show what is currently indexed."""
    tenant_id = default_tenant_id()
    with connect() as conn:
        rows = conn.execute(
            text("""
                SELECT source, status, count(*) AS documents
                  FROM documents WHERE tenant_id = :t
                 GROUP BY source, status ORDER BY source, status
            """),
            {"t": tenant_id},
        ).all()
        chunks = conn.execute(
            text("SELECT count(*) FROM chunks WHERE tenant_id = :t"), {"t": tenant_id}
        ).scalar_one()

    if not rows:
        typer.echo("nothing indexed yet")
        return

    for row in rows:
        typer.echo(f"{row.source:10} {row.status:10} {row.documents:>5} documents")
    typer.echo(f"\n{chunks} chunks total")


# Directories that are never documents. Walking them wastes time and, in the
# case of .git, produces thousands of unreadable blobs.
SKIP_DIRS = frozenset(
    {
        "node_modules",
        "__pycache__",
        "venv",
        "env",
        "dist",
        "build",
        "target",
        "site-packages",
        "vendor",
        "coverage",
        "htmlcov",
        "logs",
    }
)


def _is_ignored(path: Path, root: Path) -> bool:
    """Whether a path lies inside a directory we never index.

    Hidden entries are excluded outright. Beyond being noise, a dotfile is
    where secrets live -- indexing a project folder must not sweep up a .env.
    """
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return any(part.startswith(".") or part in SKIP_DIRS for part in parts)


def _collect(paths: list[Path], *, recursive: bool, all_files: bool = False) -> list[Path]:
    """Expand the given paths into a sorted list of ingestable files.

    Directories are filtered to formats the pipeline can actually read. Without
    that, pointing at a source tree creates hundreds of document rows purely to
    mark them skipped. A file named explicitly is always kept, so an unusual
    extension can still be forced through.

    Args:
        paths: Files or directories from the command line.
        recursive: Whether to descend into subdirectories.
        all_files: Keep every file, not just supported formats.

    Returns:
        Sorted, de-duplicated paths.
    """
    supported = supported_extensions()
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            pattern = "**/*" if recursive else "*"
            found.extend(
                p
                for p in path.glob(pattern)
                if p.is_file()
                and not _is_ignored(p, path)
                and (all_files or p.suffix.lower() in supported)
            )
        elif path.is_file():
            found.append(path)
        else:
            typer.echo(f"warning: {path} does not exist")
    return sorted(set(found))
