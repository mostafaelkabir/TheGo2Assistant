# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Database access and the migration runner.

Migrations are plain numbered ``.sql`` files applied in order and recorded in
``schema_migrations``. Alembic buys little here: most of this schema is pgvector
and generated-column DDL that would be raw SQL inside Alembic operations anyway.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, text

from go2.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Connection, Engine

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_engine: Engine | None = None


def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine, creating it on first use."""
    global _engine  # noqa: PLW0603 -- one engine per process is the point of a pool.
    if _engine is None:
        _engine = create_engine(
            get_settings().database_url,
            pool_pre_ping=True,
            future=True,
        )
    return _engine


@contextmanager
def connect() -> Iterator[Connection]:
    """Yield a connection inside a transaction, committing on clean exit."""
    with get_engine().begin() as conn:
        yield conn


def _applied_versions(conn: Connection) -> set[str]:
    conn.execute(
        text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
        """)
    )
    rows = conn.execute(text("SELECT version FROM schema_migrations")).scalars().all()
    return set(rows)


def migrate() -> list[str]:
    """Apply every unapplied migration in filename order.

    Returns:
        The versions applied by this call, in the order they ran.
    """
    applied: list[str] = []
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    with connect() as conn:
        done = _applied_versions(conn)
        for path in files:
            version = path.stem
            if version in done:
                continue
            logger.info("applying migration %s", version)
            conn.execute(text(path.read_text(encoding="utf-8")))
            conn.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:v)"),
                {"v": version},
            )
            applied.append(version)
    return applied
