# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""The background worker that drains the ingestion queue.

Embedding costs roughly a millisecond per character of text, which is fine for
one file and hours for a large folder. Rather than make that faster by giving
up model quality, ingestion is moved off the foreground: enqueue the work, walk
away, and let a worker chew through it.

Each job is claimed in its own transaction with ``FOR UPDATE SKIP LOCKED``, so
several workers can run at once and a crash mid-file leaves the job claimable
again rather than lost.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from go2.connectors.base import FetchedContent, RemoteFile
from go2.jobs.ingest import ingest_document
from go2.scope import Scope
from go2.storage import repository as repo
from go2.storage.db import connect

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

INGEST_FILE = "ingest_file"

# A file whose text is larger than this is skipped by default. One 6 MB
# markdown file costs nearly two hours to embed on CPU and would silently
# dominate a folder scan; making that a visible skip beats an invisible stall.
DEFAULT_MAX_BYTES = 2_000_000


@dataclass(frozen=True, slots=True)
class WorkerReport:
    """What one worker run accomplished."""

    processed: int = 0
    failed: int = 0
    chunks: int = 0
    seconds: float = 0.0

    @property
    def rate(self) -> float:
        """Files per minute, or 0 when nothing ran."""
        return (self.processed / self.seconds * 60) if self.seconds else 0.0


def enqueue_paths(paths: list[Path], *, tenant_id: str, source: str, account: str) -> int:
    """Queue one ingestion job per file.

    Args:
        paths: Files to ingest.
        tenant_id: Owning tenant.
        source: Connector source name.
        account: Connection account identifier.

    Returns:
        How many jobs were queued.
    """
    with connect() as conn:
        connection_id = repo.ensure_connection(
            conn, tenant_id=tenant_id, source=source, account=account
        )
        for path in paths:
            repo.enqueue_job(
                conn,
                tenant_id=tenant_id,
                kind=INGEST_FILE,
                payload={
                    "path": str(path.resolve()),
                    "connection_id": connection_id,
                    "source": source,
                },
            )
    return len(paths)


def _run_one(job: repo.Job, *, tenant_id: str, max_bytes: int) -> tuple[int, str | None]:
    """Ingest the file named by one job.

    Returns:
        ``(chunks_written, error)``. A skipped oversized file is not an error.
    """
    path = Path(str(job.payload["path"]))
    if not path.is_file():
        return 0, f"file no longer exists: {path}"

    size = path.stat().st_size
    if size > max_bytes:
        logger.warning("skipping %s: %d bytes exceeds the %d limit", path.name, size, max_bytes)
        return 0, None

    scope = Scope(
        tenant_id=tenant_id,
        connection_id=str(job.payload["connection_id"]),
        source=str(job.payload["source"]),
    )
    data = path.read_bytes()
    with connect() as conn:
        result = ingest_document(
            conn,
            scope=scope,
            remote=RemoteFile(
                external_id=str(path),
                title=path.name,
                path=str(path.parent),
                size_bytes=len(data),
            ),
            content=FetchedContent(data=data, filename=path.name, mime=""),
        )
    return result.chunks, None


def run_worker(
    *,
    tenant_id: str,
    max_bytes: int = DEFAULT_MAX_BYTES,
    once: bool = False,
    poll_seconds: float = 2.0,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> WorkerReport:
    """Drain the ingestion queue.

    Args:
        tenant_id: Owning tenant.
        max_bytes: Files larger than this are skipped rather than embedded.
        once: Stop when the queue empties instead of polling for more.
        poll_seconds: How long to wait when the queue is empty.
        on_progress: Called with ``(filename, chunks, remaining)`` per file.

    Returns:
        A summary of the run.
    """
    started = time.monotonic()
    processed = failed = chunks = 0

    while True:
        with connect() as conn:
            job = repo.claim_job(conn, tenant_id=tenant_id, kind=INGEST_FILE)

        if job is None:
            if once:
                break
            time.sleep(poll_seconds)
            continue

        name = Path(str(job.payload.get("path", "?"))).name
        try:
            written, error = _run_one(job, tenant_id=tenant_id, max_bytes=max_bytes)
        except Exception as exc:  # noqa: BLE001 -- one bad file must not stop the queue.
            written, error = 0, f"{type(exc).__name__}: {exc}"

        with connect() as conn:
            repo.finish_job(conn, job_id=job.id, error=error)
            remaining = repo.job_counts(conn, tenant_id=tenant_id).get("queued", 0)

        if error:
            failed += 1
            logger.warning("job %d failed: %s", job.id, error)
        else:
            processed += 1
            chunks += written

        if on_progress is not None:
            on_progress(name, written, remaining)

    return WorkerReport(
        processed=processed,
        failed=failed,
        chunks=chunks,
        seconds=time.monotonic() - started,
    )
