# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Command line entry point."""

from __future__ import annotations

import logging

import typer

from go2.storage.db import migrate as run_migrations

app = typer.Typer(help="Ask your assistant about your OneDrive and Google Drive files.")


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
    if applied:
        typer.echo(f"applied: {', '.join(applied)}")
    else:
        typer.echo("already up to date")
