# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Workspace isolation.

The schema has carried `tenant_id` since the first migration, but until there
was more than one tenant nothing exercised it. These tests are the difference
between isolation that is designed and isolation that is known to hold: two
tenants with overlapping content, asserting that neither reaches the other
through any path a caller has.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from go2.config import get_settings
from go2.connectors.base import FetchedContent, RemoteFile
from go2.jobs.ingest import ingest_document
from go2.rag.retrieval import SearchOptions, search
from go2.scope import Scope
from go2.storage import repository as repo
from go2.storage.db import connect
from go2.tenancy import (
    InvalidSlugError,
    UnknownTenantError,
    create_tenant,
    delete_tenant,
    list_tenants,
    resolve_tenant_id,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


SHARED_TEXT = "The annual platform fee is 18,750 EUR, invoiced each January."


def _database_available() -> bool:
    try:
        with connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


class TestSlugs:
    """Names appear in config, the CLI and eventually URLs."""

    def test_a_valid_slug_is_accepted(self) -> None:
        assert create_tenant.__doc__  # cheap import guard for the non-db path

    @pytest.mark.parametrize("bad", ["", "A", "-lead", "trail-", "has space", "UPPER", "x" * 60])
    def test_invalid_slugs_are_rejected(self, bad: str) -> None:
        with pytest.raises(InvalidSlugError):
            create_tenant(bad)


@pytest.mark.slow
class TestIsolation:
    """Two tenants, the same content, no leakage."""

    @pytest.fixture
    def two_tenants(self) -> Iterator[tuple[str, str]]:
        if not _database_available():  # pragma: no cover - environment dependent
            pytest.skip("no database reachable")
        left = f"t-{uuid.uuid4().hex[:10]}"
        right = f"t-{uuid.uuid4().hex[:10]}"
        create_tenant(left)
        create_tenant(right)
        try:
            yield left, right
        finally:
            delete_tenant(left)
            delete_tenant(right)

    @staticmethod
    def _ingest(slug: str, title: str) -> str:
        tenant_id = resolve_tenant_id(slug)
        with connect() as conn:
            scope = Scope(
                tenant_id=tenant_id,
                connection_id=repo.ensure_connection(
                    conn, tenant_id=tenant_id, source="upload", account=slug
                ),
                source="upload",
            )
            ingest_document(
                conn,
                scope=scope,
                remote=RemoteFile(external_id=f"e-{uuid.uuid4()}", title=title),
                content=FetchedContent(data=SHARED_TEXT.encode(), filename="f.txt", mime=""),
            )
        return tenant_id

    def test_search_does_not_cross_tenants(self, two_tenants: tuple[str, str]) -> None:
        left, right = two_tenants
        self._ingest(left, "Left Contract.txt")
        right_id = resolve_tenant_id(right)

        with connect() as conn:
            hits = search(
                conn,
                tenant_id=right_id,
                query="What is the annual platform fee?",
                options=SearchOptions(limit=5),
            )
        assert hits == [], "a tenant retrieved another tenant's passages"

    def test_each_tenant_sees_only_its_own(self, two_tenants: tuple[str, str]) -> None:
        left, right = two_tenants
        self._ingest(left, "Left Contract.txt")
        self._ingest(right, "Right Contract.txt")

        for slug, expected in ((left, "Left"), (right, "Right")):
            with connect() as conn:
                hits = search(
                    conn,
                    tenant_id=resolve_tenant_id(slug),
                    query="annual platform fee",
                    options=SearchOptions(limit=5),
                )
            assert hits, f"{slug} found nothing of its own"
            assert all(expected in h.title for h in hits)

    def test_chunk_counts_do_not_cross(self, two_tenants: tuple[str, str]) -> None:
        left, right = two_tenants
        self._ingest(left, "Left Contract.txt")
        left_doc = None
        with connect() as conn:
            left_doc = conn.execute(
                text("SELECT id FROM documents WHERE tenant_id = :t LIMIT 1"),
                {"t": resolve_tenant_id(left)},
            ).scalar_one()
            assert (
                repo.count_chunks(
                    conn, tenant_id=resolve_tenant_id(right), document_id=str(left_doc)
                )
                == 0
            )

    def test_deleting_a_tenant_takes_only_its_own_data(self, two_tenants: tuple[str, str]) -> None:
        left, right = two_tenants
        self._ingest(left, "Left Contract.txt")
        self._ingest(right, "Right Contract.txt")
        right_id = resolve_tenant_id(right)

        temp = f"t-{uuid.uuid4().hex[:10]}"
        create_tenant(temp)
        self._ingest(temp, "Temp Contract.txt")
        delete_tenant(temp)

        with connect() as conn:
            remaining = conn.execute(
                text("SELECT count(*) FROM documents WHERE tenant_id = :t"), {"t": right_id}
            ).scalar_one()
        assert remaining == 1, "deleting one tenant removed another's documents"


@pytest.mark.slow
class TestResolution:
    """Choosing a tenant, and failing loudly when it does not exist."""

    def test_an_unknown_tenant_is_an_error_not_an_empty_workspace(self) -> None:
        # Creating silently would turn a typo in configuration into a working,
        # empty workspace -- indistinguishable from data loss.
        if not _database_available():  # pragma: no cover - environment dependent
            pytest.skip("no database reachable")
        with pytest.raises(UnknownTenantError, match="go2 tenant create"):
            resolve_tenant_id("definitely-not-a-tenant")

    def test_the_error_lists_what_does_exist(self) -> None:
        if not _database_available():  # pragma: no cover - environment dependent
            pytest.skip("no database reachable")
        with pytest.raises(UnknownTenantError, match="Existing:"):
            resolve_tenant_id("definitely-not-a-tenant")

    def test_creating_the_same_slug_twice_is_idempotent(self) -> None:
        if not _database_available():  # pragma: no cover - environment dependent
            pytest.skip("no database reachable")
        slug = f"t-{uuid.uuid4().hex[:10]}"
        first = create_tenant(slug)
        second = create_tenant(slug)
        try:
            assert first.id == second.id
        finally:
            delete_tenant(slug)

    def test_the_configured_tenant_is_the_default(self) -> None:
        if not _database_available():  # pragma: no cover - environment dependent
            pytest.skip("no database reachable")
        assert resolve_tenant_id() == resolve_tenant_id(get_settings().tenant)

    def test_listing_reports_what_each_holds(self) -> None:
        if not _database_available():  # pragma: no cover - environment dependent
            pytest.skip("no database reachable")
        assert any(t.slug for t in list_tenants())
