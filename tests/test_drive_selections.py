# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""What a picker (T-013) recorded, through add_selections/list_selections/remove_selection.

The properties under test: a selection outlives the process that wrote it,
removing one stops it being listed active without deleting the row (so
already-indexed documents from it are never touched by this layer), and
re-picking something previously removed revives it rather than duplicating it.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from go2.storage import repository as repo
from go2.storage.db import connect
from go2.tenancy import create_tenant, delete_tenant, resolve_tenant_id

if TYPE_CHECKING:
    from collections.abc import Iterator


def _database_available() -> bool:
    try:
        with connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


@pytest.mark.slow
class TestDriveSelections:
    @pytest.fixture
    def connection(self) -> Iterator[tuple[str, str]]:
        if not _database_available():  # pragma: no cover - environment dependent
            pytest.skip("no database reachable")
        slug = f"t-{uuid.uuid4().hex[:10]}"
        create_tenant(slug)
        tenant_id = resolve_tenant_id(slug)
        with connect() as conn:
            connection_id = repo.ensure_connection(
                conn, tenant_id=tenant_id, source="gdrive", account="me@example.com"
            )
        try:
            yield tenant_id, connection_id
        finally:
            delete_tenant(slug)

    def test_the_selection_survives_a_restart(self, connection: tuple[str, str]) -> None:
        tenant_id, connection_id = connection
        with connect() as conn:
            repo.add_selections(
                conn,
                tenant_id=tenant_id,
                connection_id=connection_id,
                items=[("f-1", "file", "Contract.pdf")],
            )
        # A fresh connection stands in for a process restart.
        with connect() as conn:
            selections = repo.list_selections(conn, connection_id=connection_id)
        assert [s.external_id for s in selections] == ["f-1"]
        assert selections[0].active

    def test_only_picked_files_are_listed(self, connection: tuple[str, str]) -> None:
        tenant_id, connection_id = connection
        with connect() as conn:
            repo.add_selections(
                conn,
                tenant_id=tenant_id,
                connection_id=connection_id,
                items=[("f-1", "file", "Picked.pdf")],
            )
            selections = repo.list_selections(conn, connection_id=connection_id, active_only=True)
        assert [s.external_id for s in selections] == ["f-1"]
        # Nothing else was ever picked, so nothing else is listed -- this is
        # the property that keeps an unrelated file out of a sync's reach.

    def test_removing_a_selection_stops_it_being_listed_active(
        self, connection: tuple[str, str]
    ) -> None:
        tenant_id, connection_id = connection
        with connect() as conn:
            repo.add_selections(
                conn,
                tenant_id=tenant_id,
                connection_id=connection_id,
                items=[("f-1", "file", "Contract.pdf")],
            )
            removed = repo.remove_selection(
                conn, tenant_id=tenant_id, connection_id=connection_id, external_id="f-1"
            )
            active = repo.list_selections(conn, connection_id=connection_id, active_only=True)
            everything = repo.list_selections(conn, connection_id=connection_id)
        assert removed
        assert active == []
        # The row itself survives removal -- it is a soft stop, not a
        # delete, which is what lets already-indexed documents stay put.
        assert len(everything) == 1
        assert not everything[0].active

    def test_removing_an_already_removed_selection_reports_no_match(
        self, connection: tuple[str, str]
    ) -> None:
        tenant_id, connection_id = connection
        with connect() as conn:
            repo.add_selections(
                conn,
                tenant_id=tenant_id,
                connection_id=connection_id,
                items=[("f-1", "file", "Contract.pdf")],
            )
            repo.remove_selection(
                conn, tenant_id=tenant_id, connection_id=connection_id, external_id="f-1"
            )
            second = repo.remove_selection(
                conn, tenant_id=tenant_id, connection_id=connection_id, external_id="f-1"
            )
        assert second is False

    def test_picking_a_removed_item_again_revives_it(self, connection: tuple[str, str]) -> None:
        tenant_id, connection_id = connection
        with connect() as conn:
            repo.add_selections(
                conn,
                tenant_id=tenant_id,
                connection_id=connection_id,
                items=[("f-1", "file", "Contract.pdf")],
            )
            repo.remove_selection(
                conn, tenant_id=tenant_id, connection_id=connection_id, external_id="f-1"
            )
            repo.add_selections(
                conn,
                tenant_id=tenant_id,
                connection_id=connection_id,
                items=[("f-1", "file", "Contract.pdf")],
            )
            selections = repo.list_selections(conn, connection_id=connection_id)
        # Revived in place, not a second row.
        assert len(selections) == 1
        assert selections[0].active
