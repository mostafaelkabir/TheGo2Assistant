# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Command line entry point."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import text

from go2.connectors.base import FetchedContent, RemoteFile
from go2.extraction.registry import supported_extensions
from go2.jobs.ingest import ingest_document
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
) -> None:
    """Ingest local files through the same pipeline the connectors use.

    This is the upload path. It shares extraction, chunking, and embedding with
    Google Drive and OneDrive -- there is no separate ingestion route.
    """
    files = _collect(paths, recursive=recursive)
    if not files:
        typer.echo("nothing to ingest")
        raise typer.Exit(code=1)

    tenant_id = default_tenant_id()
    indexed = skipped = 0

    for path in files:
        with connect() as conn:
            scope = Scope(
                tenant_id=tenant_id,
                connection_id=repo.ensure_connection(
                    conn, tenant_id=tenant_id, source=UPLOAD_SOURCE, account="local"
                ),
                source=UPLOAD_SOURCE,
            )
            data = path.read_bytes()
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

        detail = f"{result.chunks} chunks"
        if result.sheets:
            detail += f", {result.sheets} sheets"
        if result.ocr_pages:
            detail += f", {result.ocr_pages} pages awaiting OCR"
        typer.echo(f"{result.status:9} {path.name}  ({detail})")

        if result.status == "skipped":
            skipped += 1
        else:
            indexed += 1

    typer.echo(f"\n{indexed} ingested, {skipped} skipped")


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


def _collect(paths: list[Path], *, recursive: bool) -> list[Path]:
    """Expand the given paths into a sorted list of ingestable files."""
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            pattern = "**/*" if recursive else "*"
            found.extend(p for p in path.glob(pattern) if p.is_file())
        elif path.is_file():
            found.append(path)
        else:
            typer.echo(f"warning: {path} does not exist")
    return sorted(set(found))
