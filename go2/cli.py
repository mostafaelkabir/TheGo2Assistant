# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Command line entry point."""

from __future__ import annotations

import logging
import time
from collections import Counter
from pathlib import Path
from typing import Annotated, Any

import typer
from sqlalchemy import text

from go2.config import get_settings
from go2.connectors.base import FetchedContent, RemoteFile
from go2.evaluation import EvalFileError, load_cases, run_all, summarise
from go2.extraction.registry import supported_extensions
from go2.jobs.ingest import IngestResult, ingest_document
from go2.jobs.worker import DEFAULT_MAX_BYTES, enqueue_paths, run_worker
from go2.observability import Trace
from go2.observability import recent as recent_traces
from go2.rag.retrieval import SearchFilters, SearchOptions
from go2.rag.retrieval import search as run_search
from go2.scope import Scope
from go2.security.pii import redact as redact_pii
from go2.security.scan import scan_files
from go2.storage import repository as repo
from go2.storage.db import connect
from go2.storage.db import migrate as run_migrations
from go2.tenancy import (
    InvalidSlugError,
    UnknownTenantError,
    create_tenant,
    delete_tenant,
    list_tenants,
    resolve_tenant_id,
)
from go2.tools.search import list_documents as _list_documents
from go2.tools.search import unsearchable_count

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

    tenant_id = resolve_tenant_id()

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
    tenant_id = resolve_tenant_id()
    recorder = Trace(kind="search", label=query)
    started = time.perf_counter()
    with connect() as conn:
        hits = run_search(
            conn,
            tenant_id=tenant_id,
            query=query,
            filters=SearchFilters(source=source or None),
            options=SearchOptions(limit=limit, rerank=not no_rerank, trace=recorder),
        )
    threshold = get_settings().min_evidence_score
    best = hits[0].score if hits else None
    recorder.duration_ms = (time.perf_counter() - started) * 1000
    recorder.outcome = "answered" if best is not None and best >= threshold else "refused"
    recorder.meta = {"threshold": threshold, "best_score": best, "returned": len(hits)}
    recorder.save(tenant_id=tenant_id)

    if not hits:
        with connect() as conn:
            stranded = unsearchable_count(conn, tenant_id)
        if stranded:
            # The usual cause is running from a directory where the config was
            # not found, so a different provider is active than the one that
            # produced these vectors.
            typer.echo(
                f"no matches — but {stranded} documents are indexed under a different "
                f"embedding model.\n"
                f"active model: {get_settings().active_embedding_model}\n"
                f"Either re-ingest, or point at the config that was used to index them "
                f"(~/.config/go2/.env)."
            )
        else:
            typer.echo("no matches")
        return

    for rank, hit in enumerate(hits, start=1):
        snippet = " ".join(hit.text.split())[:220]
        typer.echo(f"\n{rank}. {hit.citation()}   [{hit.score:.3f}]")
        typer.echo(f"   {snippet}...")


@app.command()
def scan(
    paths: Annotated[list[Path], typer.Argument(help="Files or directories to scan.")],
    *,
    show: Annotated[
        bool, typer.Option("--show", help="Print a redacted excerpt around each finding.")
    ] = False,
) -> None:
    """Report sensitive values in files, without ingesting anything.

    Run this before pointing a connector at a new source. It reads locally and
    sends nothing anywhere, so it is safe on material you have not decided to
    index yet.
    """
    files = _collect(paths, recursive=True)
    if not files:
        typer.echo("nothing to scan")
        raise typer.Exit(code=1)

    report = scan_files(files)

    for entry in report.files:
        detail = ", ".join(f"{n} {k}" for k, n in sorted(entry.counts.items()))
        typer.echo(f"{entry.path.name}  ({detail})")
        if show:
            for finding in entry.findings[:3]:
                excerpt = entry.body[max(0, finding.start - 40) : finding.end + 20]
                masked, _ = redact_pii(" ".join(excerpt.split()))
                typer.echo(f"    …{masked}…")

    settings = get_settings()
    typer.echo(f"\n{len(report.files)} of {report.scanned} files contain sensitive values")
    for kind, number in sorted(report.totals.items(), key=lambda kv: -kv[1]):
        typer.echo(f"  {number:>5}  {kind}")
    if report.unreadable:
        typer.echo(f"  {report.unreadable} files could not be read and were not scanned")
    typer.echo(f"\npolicy: {settings.pii_policy}  |  provider: {settings.embedding_provider}")
    if settings.embedding_provider == "local":
        typer.echo("nothing leaves this machine under the local provider.")


@app.command()
def evaluate(
    path: Annotated[Path, typer.Argument(help="YAML file of eval cases.")] = Path(
        "eval/questions.yaml"
    ),
    *,
    limit: Annotated[int, typer.Option(help="Hits to consider per question.")] = 5,
    verbose: Annotated[bool, typer.Option("--verbose", help="Show what came back.")] = False,
) -> None:
    """Check retrieval against known question/document pairs.

    Retrieval regressions are silent -- the system keeps returning
    confident-looking passages, just the wrong ones. Running this after any
    change to chunking, embedding, or reranking is what turns that into a
    number you can compare.
    """
    try:
        cases = load_cases(path)
    except EvalFileError as exc:
        typer.echo(
            f"{exc}\n\nCreate one like:\n"
            "  - question: How much did the pipeline cost?\n"
            "    expect_document: RESUME_CONTEXT\n"
            '    expect_text: "507"        # optional'
        )
        raise typer.Exit(code=1) from exc

    outcomes = run_all(cases, limit=limit)
    for outcome in outcomes:
        mark = "PASS" if outcome.passed else "FAIL"
        if outcome.case.expect_no_answer:
            marker = "refuse" if not outcome.sufficient else "ANSWERED"
            typer.echo(f"{mark} {marker:>8}  {outcome.case.question}")
        else:
            rank = f"@{outcome.rank}" if outcome.rank else "--"
            typer.echo(f"{mark} {rank:>8}  {outcome.case.question}")
        if not outcome.passed or verbose:
            if outcome.case.expect_no_answer:
                typer.echo(f"          expected: no answer (score {outcome.top_score:.2f})")
            else:
                typer.echo(f"          expected: {outcome.case.expect_document}")
            typer.echo(f"          returned: {', '.join(outcome.returned[:4]) or '(nothing)'}")
            if outcome.case.expect_text and not outcome.text_found:
                typer.echo(f"          missing text: {outcome.case.expect_text!r}")

    stats = summarise(outcomes)
    typer.echo(
        f"\n{stats['passed']}/{stats['total']} passed"
        f"  |  {stats['top1']} at rank 1"
        f"  |  MRR {stats['mrr']:.2f}"
    )
    if stats["refusals"]:
        margin = stats["min_accepted"] - stats["max_refused"]
        typer.echo(
            f"refusals: {stats['refused_correctly']}/{stats['refusals']} correct"
            f"  |  weakest accepted {stats['min_accepted']:.2f}"
            f"  |  strongest refused {stats['max_refused']:.2f}"
            f"  |  margin {margin:+.2f}"
        )
        if margin <= 0:
            typer.echo(
                "  warning: the bands overlap — no single threshold separates "
                "answerable from unanswerable on these cases."
            )
    if stats["passed"] < stats["total"]:
        raise typer.Exit(code=1)


@app.command()
def serve(
    *,
    http: Annotated[
        bool, typer.Option("--http", help="Serve over Streamable HTTP instead of stdio.")
    ] = False,
    host: Annotated[str, typer.Option(help="Interface to bind under --http.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to bind under --http.")] = 8765,
    allow_host: Annotated[
        list[str] | None,
        typer.Option(
            "--allow-host",
            help="Extra Host header to accept, e.g. host.docker.internal:8765. Repeatable.",
        ),
    ] = None,
) -> None:
    """Run the MCP server.

    Default is stdio, for a client that launches this process itself -- Claude
    Code and Claude Desktop both do. ``--http`` is for a client that cannot,
    such as a chat UI in a container, which has no `go2` and no route to
    Postgres of its own.
    """
    if not http:
        from go2.mcp_server import main as run_server  # noqa: PLC0415 -- defer the mcp import.

        run_server()
        return

    from go2.mcp_server import run_http  # noqa: PLC0415 -- defer the mcp import.

    tenant = get_settings().tenant
    typer.echo(f"go2assistant MCP on http://{host}:{port}/mcp  (tenant: {tenant})")
    if host not in {"127.0.0.1", "localhost"}:
        typer.echo(
            "warning: binding beyond loopback exposes the whole index -- "
            "there is no authentication in front of this yet.",
            err=True,
        )
    run_http(host=host, port=port, allowed_hosts=list(allow_host or []))


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
    tenant_id = resolve_tenant_id()
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
    tenant_id = resolve_tenant_id()
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
def docs(
    contains: Annotated[str, typer.Option(help="Only titles containing this text.")] = "",
    source: Annotated[str, typer.Option(help="Only this connector.")] = "",
    doc_status: Annotated[str, typer.Option("--status", help="Only this status.")] = "",
    *,
    by_folder: Annotated[
        bool, typer.Option("--by-folder", help="Group by directory instead of listing.")
    ] = False,
    limit: Annotated[int, typer.Option(help="Maximum rows.")] = 500,
) -> None:
    """List the documents that have been ingested.

    This is the file-level view: which files the assistant actually has, where
    they came from, and how much of each was indexed. A file with 0 chunks is
    not a failure -- a spreadsheet is kept whole as a sheet rather than being
    chunked as prose.
    """
    rows = _list_documents(
        source=source or None,
        title_contains=contains or None,
        status=doc_status or None,
        limit=limit,
    )
    if not rows:
        typer.echo("no documents match")
        return

    if by_folder:
        grouped: Counter[str] = Counter()
        chunks: Counter[str] = Counter()
        for row in rows:
            grouped[row["path"]] += 1
            chunks[row["path"]] += int(row["chunks"])
        for folder, count in grouped.most_common():
            typer.echo(f"{count:>4} files {chunks[folder]:>6} chunks   {folder}")
    else:
        for row in sorted(rows, key=lambda r: str(r["title"]).lower()):
            typer.echo(f"{row['chunks']:>4} chunks  {row['status']:<8} {row['title']}")

    total = sum(int(r["chunks"]) for r in rows)
    typer.echo(f"\n{len(rows)} documents, {total} chunks")


@app.command()
def trace(
    *,
    last: Annotated[int, typer.Option(help="How many recent requests to show.")] = 3,
) -> None:
    """Show what each component did with the data, for recent requests.

    Application logs record that a request arrived and a response left. This
    records the path between: which component ran, what it received, what it
    produced, how long it took, and whether it sent anything off the machine.
    """
    entries = recent_traces(resolve_tenant_id(), limit=last)
    if not entries:
        typer.echo("no traces recorded yet — run a search first")
        return

    for entry in entries:
        stamp = entry["created_at"].strftime("%H:%M:%S")
        verdict = entry["outcome"] or "?"
        typer.echo(
            f"\n{stamp}  {verdict.upper():8}  {entry['duration_ms']:.0f} ms   {entry['label'][:58]}"
        )
        total = max(entry["duration_ms"] or 1.0, 1.0)
        for step in entry["steps"]:
            share = step["duration_ms"] / total
            bar = "█" * max(1, round(share * 22))
            flag = " → LEAVES MACHINE" if step["egress"] else ""
            typer.echo(
                f"  {step['component']:<18} {step['duration_ms']:>7.0f} ms "
                f"{bar:<22} {share * 100:>4.0f}%{flag}"
            )
            typer.echo(f"      in  {_facts(step['input'])}")
            typer.echo(f"      out {_facts(step['output'])}")


def _facts(payload: dict[str, Any]) -> str:
    """Render a step's recorded facts on one line."""
    if not payload:
        return "-"
    return "  ".join(f"{k}={v}" for k, v in payload.items())


tenant_app = typer.Typer(help="Isolated workspaces. Each holds its own documents and index.")
app.add_typer(tenant_app, name="tenant")


@tenant_app.command("list")
def tenant_list() -> None:
    """Show every workspace and how much each holds."""
    active = get_settings().tenant
    for tenant in list_tenants():
        marker = "*" if tenant.slug == active else " "
        typer.echo(
            f"{marker} {tenant.slug:<20} {tenant.documents:>5} documents {tenant.chunks:>7} chunks"
        )
    typer.echo(f"\n* = active (GO2_TENANT={active})")


@tenant_app.command("create")
def tenant_create(slug: Annotated[str, typer.Argument(help="Name for the workspace.")]) -> None:
    """Create an empty workspace."""
    try:
        tenant = create_tenant(slug)
    except InvalidSlugError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"created {tenant.slug}\n\n"
        f"Use it by setting GO2_TENANT={tenant.slug} — in the shell, in a project-local\n"
        f".env, or in ~/.config/go2/.env to make it the default."
    )


@tenant_app.command("current")
def tenant_current() -> None:
    """Show the active workspace and what it contains."""
    slug = get_settings().tenant
    try:
        resolve_tenant_id()
    except UnknownTenantError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    match = next((t for t in list_tenants() if t.slug == slug), None)
    if match:
        typer.echo(f"{match.slug}: {match.documents} documents, {match.chunks} chunks")


@tenant_app.command("delete")
def tenant_delete(
    slug: Annotated[str, typer.Argument(help="Workspace to remove.")],
    *,
    yes: Annotated[bool, typer.Option("--yes", help="Skip the confirmation.")] = False,
) -> None:
    """Permanently remove a workspace and everything in it."""
    try:
        target = next((t for t in list_tenants() if t.slug == slug), None)
        if target is None:
            resolve_tenant_id(slug)  # raises with the available list
            return
        if not yes:
            typer.echo(
                f"{slug} holds {target.documents} documents and {target.chunks} chunks.\n"
                f"This cannot be undone. Re-run with --yes to confirm."
            )
            raise typer.Exit(code=1)
        removed = delete_tenant(slug)
    except UnknownTenantError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    typer.echo(f"removed {slug} and its {removed} documents")


@app.command()
def status() -> None:
    """Show what is currently indexed."""
    tenant_id = resolve_tenant_id()
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

    active = get_settings().active_embedding_model
    with connect() as conn:
        stale = conn.execute(
            text("""
                SELECT count(*) FROM documents
                 WHERE tenant_id = :t AND embedding_model IS DISTINCT FROM :m
            """),
            {"t": tenant_id, "m": active},
        ).scalar_one()
    typer.echo(f"embeddings: {active}")
    if stale:
        # Vectors from another model are unsearchable rather than wrong, but
        # silently unsearchable is its own kind of wrong.
        typer.echo(
            f"\nwarning: {stale} documents were embedded with a different model and "
            f"cannot be searched.\n         re-ingest them, or switch the provider back."
        )


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
