# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Mirror the backlog into Basira, the owner's local tracking app.

The repository's ``backlog/`` stays the record: it is what CI checks and
what a pull request updates. Basira is where the owner watches progress and
decides what is next, so every ticket file is pushed there as a work ticket
under one company and one project goal, keyed on ``ticket_ref`` = the
ticket id. The push is idempotent -- a second run with nothing changed makes
no write -- so it can follow every ticket edit the way ``go2 backlog index``
does.

One direction only. A status moved in Basira is a prompt for whoever picks
the work up, not a write into the ticket file; and a Basira ticket with no
``T-NNN`` ref is reported, so a request the owner types into the app becomes
a repository ticket rather than being lost.

Basira answers on loopback without authentication and holds only ticket
text, so nothing here passes through the egress guard: no document content
is involved and nothing leaves the machine. That exemption holds only while
``GO2_BASIRA_URL`` is local, so :func:`sync` refuses a URL whose host does not
resolve to loopback rather than becoming an unguarded egress path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from go2.backlog import ID_PATTERN
from go2.security.loopback import is_loopback

if TYPE_CHECKING:
    from collections.abc import Sequence

    from go2.backlog import Ticket

# Basira's own vocabulary, read from its OpenAPI schema and the values in use.
STATUS = {
    "backlog": "backlog",
    "ready": "todo",
    "in-progress": "in_progress",
    "in-review": "review",
    "done": "done",
    "dropped": "done",
}
PRIORITY = {"P0": "urgent", "P1": "high", "P2": "medium", "P3": "low"}
# Fields the mirror owns on a Basira ticket. Anything else there (time logged,
# comments, proofs the owner attached by hand) is left alone.
OWNED = (
    "company_id",
    "linked_goal_id",
    "title",
    "description",
    "type",
    "status",
    "priority",
    "ticket_ref",
    "tags",
    "notes",
)
_TIMEOUT = httpx.Timeout(10.0, connect=3.0)
# The label on the proof this module writes, so it can replace its own and
# leave anything the owner attached by hand alone.
PR_PROOF_LABEL = "Pull request"


class BasiraError(RuntimeError):
    """Basira could not be reached or refused a request."""


@dataclass(frozen=True, slots=True)
class Target:
    """Where the mirror writes: one Basira, one company, one goal."""

    url: str
    company_id: str
    goal_id: str


@dataclass
class SyncReport:
    """What one run did, or would do under ``dry_run``."""

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    # Titles of Basira tickets in the company that carry no repository id.
    unmatched: list[str] = field(default_factory=list)
    # Ids carried by more than one Basira ticket. Only one is kept in step;
    # the rest are drift to clean up in the app.
    duplicated: list[str] = field(default_factory=list)
    # For each updated id, the owned fields that differed: name -> (basira,
    # file). A status the owner moved in Basira shows up here before the file
    # overwrites it, which is the prompt to update the file instead.
    changes: dict[str, dict[str, tuple[Any, Any]]] = field(default_factory=dict)

    @property
    def writes(self) -> int:
        """How many requests changed something."""
        return len(self.created) + len(self.updated)


def desired(ticket: Ticket, target: Target, *, open_ids: set[str]) -> dict[str, Any]:
    """The Basira ticket a repository ticket should be mirrored as.

    Args:
        ticket: The parsed ticket file.
        target: Company and goal to file it under.
        open_ids: Ids of every ticket still open, to decide the ``blocked`` tag.
    """
    tags = [ticket.phase]
    if any(blocker in open_ids for blocker in ticket.blocked_by):
        tags.append("blocked")
    if ticket.status == "dropped":
        tags.append("dropped")

    parts = []
    for heading in ("Problem", "Definition"):
        text = ticket.sections.get(heading, "").strip()
        if text:
            parts.append(f"## {heading}\n\n{text}")
    parts.append(f"Ticket file: backlog/{ticket.link}")
    if ticket.github_issue:
        parts.append(f"GitHub issue: #{ticket.github_issue}")

    notes = [
        f"{name}: {value}"
        for name, value in (("owner", ticket.owner), ("branch", ticket.branch), ("pr", ticket.pr))
        if value
    ]

    return {
        "company_id": target.company_id,
        "linked_goal_id": target.goal_id,
        "title": f"{ticket.id} {ticket.title}",
        "description": "\n\n".join(parts),
        "type": "planning" if ticket.phase == "0-process" else "code",
        "status": STATUS[ticket.status],
        "priority": PRIORITY[ticket.priority],
        "ticket_ref": ticket.id,
        "tags": tags,
        "notes": "\n".join(notes),
    }


def differences(existing: dict[str, Any], wanted: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """Owned fields where Basira and the file disagree: name -> (basira, file)."""
    return {
        key: (existing.get(key), wanted[key]) for key in OWNED if existing.get(key) != wanted[key]
    }


def _proofs(existing: dict[str, Any] | None, ticket: Ticket) -> list[dict[str, str]] | None:
    """The proofs list with the ticket's PR as its one generated proof, or None if unchanged.

    Hand-added proofs are kept. An earlier generated proof for a different
    PR URL is replaced, so a corrected ``pr:`` does not leave a stale link.
    """
    if not ticket.pr:
        return None
    current = list((existing or {}).get("proofs") or [])
    generated = {"url": ticket.pr, "label": PR_PROOF_LABEL}
    if generated in current:
        return None
    kept = [p for p in current if p.get("label") != PR_PROOF_LABEL]
    return [*kept, generated]


def sync(
    tickets: Sequence[Ticket],
    target: Target,
    *,
    dry_run: bool = False,
    client: httpx.Client | None = None,
) -> SyncReport:
    """Push every ticket to Basira, creating or updating by ``ticket_ref``.

    Args:
        tickets: The repository's tickets, as ``go2.backlog.load_tickets`` returns them.
        target: Basira, company and goal to write under.
        dry_run: Report the plan and make no write.
        client: An HTTP client to use instead of a real one, for tests.

    Returns:
        What was created, updated, left alone, and what Basira holds that the
        repository does not.

    Raises:
        BasiraError: If ``target.url`` is not loopback, or Basira cannot be
            reached or refuses a request. Each ticket is a single request,
            so a failure never leaves one half written.
    """
    host = httpx.URL(target.url).host
    if not is_loopback(host):
        msg = (
            f"refusing to sync to {target.url}: Basira must be local. Ticket text would "
            f"otherwise leave the machine without passing the egress guard."
        )
        raise BasiraError(msg)
    owns = client is None
    http = client or httpx.Client(base_url=target.url, timeout=_TIMEOUT)
    run = _Run(
        http=http, target=target, open_ids={t.id for t in tickets if t.is_open}, dry_run=dry_run
    )
    report = run.report
    try:
        # The API filters by company; the client-side check keeps a Basira
        # that ignored the parameter from pulling other clients' tickets in.
        existing = [
            t
            for t in _get(http, "/work-tickets", company_id=target.company_id)
            if t.get("company_id") == target.company_id
        ]
        by_ref = _index(existing, report)
        for ticket in tickets:
            run.push(ticket, by_ref.get(ticket.id))
    finally:
        if owns:
            http.close()
    return report


def _index(existing: list[dict[str, Any]], report: SyncReport) -> dict[str, dict[str, Any]]:
    """Basira tickets by repository id, noting what has none and what has two."""
    by_ref: dict[str, dict[str, Any]] = {}
    for t in existing:
        ref = t.get("ticket_ref") or ""
        if not ID_PATTERN.match(ref):
            report.unmatched.append(t["title"])
        elif ref in by_ref:
            report.duplicated.append(ref)
        else:
            by_ref[ref] = t
    return by_ref


@dataclass
class _Run:
    """One sync pass: the client, where it writes, and what it has done."""

    http: httpx.Client
    target: Target
    open_ids: set[str]
    dry_run: bool
    report: SyncReport = field(default_factory=SyncReport)

    def push(self, ticket: Ticket, current: dict[str, Any] | None) -> None:
        """Create, update or leave one ticket, and record which."""
        wanted = desired(ticket, self.target, open_ids=self.open_ids)
        proofs = _proofs(current, ticket)
        if proofs is not None:
            wanted["proofs"] = proofs
        if current is None:
            self.report.created.append(ticket.id)
            if not self.dry_run:
                _send(self.http, "POST", "/work-tickets", wanted)
            return
        changed = differences(current, wanted)
        if not changed and proofs is None:
            self.report.unchanged.append(ticket.id)
            return
        self.report.updated.append(ticket.id)
        if changed:
            self.report.changes[ticket.id] = changed
        if not self.dry_run:
            _send(self.http, "PUT", f"/work-tickets/{current['id']}", wanted)


def _get(http: httpx.Client, path: str, **params: str) -> list[dict[str, Any]]:
    try:
        response = http.get(path, params=params)
    except httpx.HTTPError as exc:
        msg = f"could not reach Basira at {http.base_url}: {exc}"
        raise BasiraError(msg) from exc
    if response.status_code != httpx.codes.OK:
        msg = f"Basira returned {response.status_code} for GET {path}: {response.text[:200]}"
        raise BasiraError(msg)
    return list(response.json())


def _send(http: httpx.Client, method: str, path: str, payload: dict[str, Any]) -> None:
    try:
        response = http.request(method, path, json=payload)
    except httpx.HTTPError as exc:
        msg = f"could not reach Basira at {http.base_url}: {exc}"
        raise BasiraError(msg) from exc
    if response.status_code >= httpx.codes.BAD_REQUEST:
        msg = f"Basira returned {response.status_code} for {method} {path}: {response.text[:200]}"
        raise BasiraError(msg)
