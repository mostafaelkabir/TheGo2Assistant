# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""The ownership context every write and query is scoped by.

This is the multi-tenancy seam. Today ``tenant_id`` is always the single local
tenant, but because every repository call takes a ``Scope`` rather than loose
identifiers, becoming multi-tenant means resolving this object from a request
instead of auditing every call site.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Scope:
    """Who owns a document and where it came from."""

    tenant_id: str
    connection_id: str
    source: str
