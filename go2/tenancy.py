# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Resolving which tenant a request belongs to.

The storage layer has been multi-tenant since the first migration: every table
carries ``tenant_id`` and every query filters on it. What was missing was
anything that *chose* a tenant -- every entry point resolved the same hardcoded
``local`` row, so the isolation was real but unused.

This is the seam that fills that gap. Today the tenant comes from
configuration, because there is one operator working across several projects.
When there are several operators it comes from the authenticated principal
instead, and nothing below this module changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text

from go2.config import get_settings
from go2.storage.db import connect

# Slugs appear in configuration, in the CLI and eventually in URLs, so they are
# kept to a shape that is unambiguous in all three.
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]$")


@dataclass(frozen=True, slots=True)
class Tenant:
    """One isolated workspace."""

    id: str
    slug: str
    documents: int = 0
    chunks: int = 0


class UnknownTenantError(RuntimeError):
    """Raised when the configured tenant does not exist."""

    def __init__(self, slug: str, available: list[str]) -> None:
        """Name the missing tenant, what does exist, and how to create it."""
        known = ", ".join(available) if available else "none"
        super().__init__(
            f"no tenant {slug!r}. Existing: {known}. "
            f"Create it with `go2 tenant create {slug}`, or set GO2_TENANT to an existing one."
        )


class InvalidSlugError(ValueError):
    """Raised when a tenant slug is not usable."""

    def __init__(self, slug: str) -> None:
        """Explain the accepted shape."""
        super().__init__(
            f"{slug!r} is not a valid tenant name. Use lowercase letters, digits and "
            f"hyphens, 2-40 characters, starting and ending with a letter or digit."
        )


def resolve_tenant_id(slug: str | None = None) -> str:
    """Return the id of the active tenant.

    Args:
        slug: Tenant to resolve. Defaults to the configured one.

    Returns:
        The tenant's id.

    Raises:
        UnknownTenantError: If no such tenant exists. Deliberately an error
            rather than silently creating one -- a typo in configuration would
            otherwise produce a working, empty workspace, which looks exactly
            like data loss.
    """
    wanted = slug or get_settings().tenant
    with connect() as conn:
        row = conn.execute(
            text("SELECT id FROM tenants WHERE slug = :s"), {"s": wanted}
        ).scalar_one_or_none()
        if row is None:
            available = list(
                conn.execute(text("SELECT slug FROM tenants ORDER BY slug")).scalars().all()
            )
            raise UnknownTenantError(wanted, available)
    return str(row)


def create_tenant(slug: str) -> Tenant:
    """Create an empty tenant.

    Args:
        slug: Name for the new workspace.

    Returns:
        The tenant, whether newly created or already present.

    Raises:
        InvalidSlugError: If the slug is not usable.
    """
    if not SLUG.match(slug):
        raise InvalidSlugError(slug)
    with connect() as conn:
        row = conn.execute(
            text("""
                INSERT INTO tenants (slug) VALUES (:s)
                ON CONFLICT (slug) DO UPDATE SET slug = EXCLUDED.slug
                RETURNING id
            """),
            {"s": slug},
        ).scalar_one()
    return Tenant(id=str(row), slug=slug)


def list_tenants() -> list[Tenant]:
    """Every tenant, with how much each holds."""
    with connect() as conn:
        rows = conn.execute(
            text("""
                SELECT t.id, t.slug,
                       (SELECT count(*) FROM documents d WHERE d.tenant_id = t.id) AS docs,
                       (SELECT count(*) FROM chunks c WHERE c.tenant_id = t.id) AS chunks
                  FROM tenants t ORDER BY t.slug
            """)
        ).all()
    return [
        Tenant(id=str(r.id), slug=r.slug, documents=int(r.docs), chunks=int(r.chunks)) for r in rows
    ]


def delete_tenant(slug: str) -> int:
    """Remove a tenant and everything it holds.

    Returns:
        How many documents were removed with it.

    Raises:
        UnknownTenantError: If no such tenant exists.
    """
    tenant_id = resolve_tenant_id(slug)
    with connect() as conn:
        count = int(
            conn.execute(
                text("SELECT count(*) FROM documents WHERE tenant_id = :t"), {"t": tenant_id}
            ).scalar_one()
        )
        # Documents, chunks, jobs, connections and traces all cascade from here.
        conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
    return count
