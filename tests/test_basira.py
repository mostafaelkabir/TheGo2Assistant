# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""The Basira mirror.

Exercised against a fake Basira behind ``httpx.MockTransport``: a dict of
work tickets and the three routes the mirror uses. No network, no app.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from go2.backlog import Ticket
from go2.basira import BasiraError, SyncReport, Target, desired, sync

TARGET = Target(url="http://basira.test", company_id="company-1", goal_id="goal-1")


class FakeBasira:
    """Enough of the Work API to mirror against."""

    def __init__(self, tickets: list[dict[str, Any]] | None = None) -> None:
        self.tickets: dict[str, dict[str, Any]] = {t["id"]: t for t in tickets or []}
        self.requests: list[tuple[str, str]] = []
        self._next = 1

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path == "/work-tickets":
            return httpx.Response(200, json=list(self.tickets.values()))
        if request.method == "POST" and request.url.path == "/work-tickets":
            body = json.loads(request.content)
            body["id"] = f"b-{self._next}"
            self._next += 1
            body.setdefault("proofs", [])
            self.tickets[body["id"]] = body
            return httpx.Response(200, json=body)
        if request.method == "PUT" and request.url.path.startswith("/work-tickets/"):
            ticket_id = request.url.path.rsplit("/", 1)[1]
            self.tickets[ticket_id].update(json.loads(request.content))
            return httpx.Response(200, json=self.tickets[ticket_id])
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(base_url=TARGET.url, transport=httpx.MockTransport(self.handle))

    def by_ref(self, ref: str) -> dict[str, Any]:
        return next(t for t in self.tickets.values() if t.get("ticket_ref") == ref)


def _ticket(
    ticket_id: str = "T-001",
    *,
    status: str = "ready",
    priority: str = "P2",
    blocked_by: list[str] | None = None,
    pr: str | None = None,
) -> Ticket:
    return Ticket(
        path=Path(f"backlog/tickets/{ticket_id}-a-ticket.md"),
        id=ticket_id,
        title="A ticket",
        status=status,
        phase="1-drive",
        priority=priority,
        created=date(2026, 9, 16),
        updated=date(2026, 9, 16),
        blocked_by=blocked_by or [],
        pr=pr,
        sections={"Problem": "Something is wrong.", "Definition": "Fix it."},
    )


def test_a_new_ticket_is_created_with_its_ref_and_goal() -> None:
    basira = FakeBasira()
    report = sync([_ticket()], TARGET, client=basira.client())
    assert report.created == ["T-001"]
    created = basira.by_ref("T-001")
    assert created["linked_goal_id"] == "goal-1"
    assert created["company_id"] == "company-1"
    assert created["title"] == "T-001 A ticket"
    assert "Something is wrong." in created["description"]
    assert "backlog/tickets/T-001-a-ticket.md" in created["description"]


def test_an_existing_ticket_is_updated_not_duplicated() -> None:
    basira = FakeBasira()
    sync([_ticket(status="ready")], TARGET, client=basira.client())
    report = sync([_ticket(status="in-progress")], TARGET, client=basira.client())
    assert report.updated == ["T-001"]
    assert report.created == []
    assert len(basira.tickets) == 1
    assert basira.by_ref("T-001")["status"] == "in_progress"


def test_an_unchanged_ticket_makes_no_request() -> None:
    basira = FakeBasira()
    sync([_ticket()], TARGET, client=basira.client())
    basira.requests.clear()
    report = sync([_ticket()], TARGET, client=basira.client())
    assert report.unchanged == ["T-001"]
    assert report.writes == 0
    # One read to learn what is there, and nothing else.
    assert basira.requests == [("GET", "/work-tickets")]


@pytest.mark.parametrize(
    ("status", "priority", "expected_status", "expected_priority"),
    [
        ("backlog", "P3", "backlog", "low"),
        ("ready", "P2", "todo", "medium"),
        ("in-progress", "P1", "in_progress", "high"),
        ("in-review", "P0", "review", "urgent"),
        ("done", "P2", "done", "medium"),
    ],
)
def test_status_and_priority_map_to_basira_vocabulary(
    status: str, priority: str, expected_status: str, expected_priority: str
) -> None:
    wanted = desired(_ticket(status=status, priority=priority), TARGET, open_ids=set())
    assert wanted["status"] == expected_status
    assert wanted["priority"] == expected_priority


def test_a_dropped_ticket_is_done_with_a_tag() -> None:
    # Basira has no "dropped"; done plus a tag keeps it out of the queue
    # without pretending it shipped.
    wanted = desired(_ticket(status="dropped"), TARGET, open_ids=set())
    assert wanted["status"] == "done"
    assert "dropped" in wanted["tags"]


def test_an_open_blocker_adds_the_blocked_tag() -> None:
    blocked = _ticket("T-002", status="backlog", blocked_by=["T-001"])
    assert "blocked" in desired(blocked, TARGET, open_ids={"T-001"})["tags"]
    # A closed blocker is no blocker.
    assert "blocked" not in desired(blocked, TARGET, open_ids=set())["tags"]


def test_a_dry_run_writes_nothing() -> None:
    basira = FakeBasira()
    report = sync([_ticket()], TARGET, dry_run=True, client=basira.client())
    assert report.created == ["T-001"]
    assert basira.tickets == {}
    assert basira.requests == [("GET", "/work-tickets")]


def test_basira_tickets_without_a_ref_are_reported() -> None:
    basira = FakeBasira(
        [
            {"id": "b-9", "company_id": "company-1", "ticket_ref": "", "title": "Typed in the app"},
            {"id": "b-8", "company_id": "other", "ticket_ref": "", "title": "Another company"},
        ]
    )
    report = sync([], TARGET, client=basira.client())
    assert report.unmatched == ["Typed in the app"]


def test_the_pull_request_becomes_a_proof_once() -> None:
    basira = FakeBasira()
    sync([_ticket(status="in-review", pr="https://example/pr/1")], TARGET, client=basira.client())
    basira.by_ref("T-001")["proofs"].append({"url": "https://example/shot.png", "label": "by hand"})
    report = sync(
        [_ticket(status="in-review", pr="https://example/pr/1")], TARGET, client=basira.client()
    )
    assert report.unchanged == ["T-001"]
    urls = [p["url"] for p in basira.by_ref("T-001")["proofs"]]
    assert urls == ["https://example/pr/1", "https://example/shot.png"]


def test_an_unreachable_basira_names_the_url() -> None:
    def refuse(_request: httpx.Request) -> httpx.Response:
        msg = "refused"
        raise httpx.ConnectError(msg)

    client = httpx.Client(base_url=TARGET.url, transport=httpx.MockTransport(refuse))
    with pytest.raises(BasiraError, match=r"basira\.test"):
        sync([_ticket()], TARGET, client=client)


def test_a_refused_write_is_an_error_not_a_silent_skip() -> None:
    def bad_request(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(422, json={"detail": "company_id required"})

    client = httpx.Client(base_url=TARGET.url, transport=httpx.MockTransport(bad_request))
    with pytest.raises(BasiraError, match="422"):
        sync([_ticket()], TARGET, client=client)


def test_the_report_counts_writes() -> None:
    report = SyncReport(created=["T-001"], updated=["T-002", "T-003"], unchanged=["T-004"])
    assert report.writes == 3
