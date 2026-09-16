# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""The ticket store's own rules.

A file-based backlog shared by several agents is only as good as what it
refuses: an in-progress ticket with no owner is one a second agent takes, a
done ticket with no outcome is one nobody learns from, and a stale index
is a queue that lies. The last test runs the check against the committed
backlog, so a malformed ticket fails CI.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from go2.backlog import (
    TicketError,
    check,
    load_tickets,
    new_ticket_text,
    next_id,
    parse_ticket,
    ready,
    render_index,
    slugify,
    write_index,
)
from go2.cli import app

if TYPE_CHECKING:
    from pathlib import Path

TODAY = date(2026, 9, 16)


def _ticket(
    ticket_id: str = "T-001",
    *,
    status: str = "backlog",
    extra_meta: str = "",
    outcome: str = "",
    problem: str = "Something is wrong.",
) -> str:
    return f"""---
id: {ticket_id}
title: A ticket
status: {status}
phase: 1-drive
priority: P2
blocked_by: []
{extra_meta}
created: 2026-09-16
updated: 2026-09-16
---

## Problem

{problem}

## Definition

Do the thing.

## Success metrics

- It is done.

## Test cases

- `test_it`

## Work log

- 2026-09-16 — opened.

## Outcome

{outcome}
"""


def _write(root: Path, name: str, text: str) -> Path:
    folder = root / "tickets"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def test_a_valid_ticket_parses(tmp_path: Path) -> None:
    path = _write(tmp_path, "T-001-a-ticket.md", _ticket())
    t = parse_ticket(path)
    assert t.id == "T-001"
    assert t.status == "backlog"
    assert t.is_open
    assert t.sections["Problem"] == "Something is wrong."


def test_a_missing_section_is_rejected(tmp_path: Path) -> None:
    text = _ticket().replace("## Success metrics\n\n- It is done.\n", "")
    path = _write(tmp_path, "T-001-a-ticket.md", text)
    with pytest.raises(TicketError, match="Success metrics"):
        parse_ticket(path)


def test_an_empty_problem_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "T-001-a-ticket.md", _ticket(problem=""))
    with pytest.raises(TicketError, match="wish"):
        parse_ticket(path)


def test_an_unknown_phase_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "T-001-a-ticket.md", _ticket().replace("1-drive", "1-drvie"))
    with pytest.raises(TicketError, match="phase '1-drvie'"):
        parse_ticket(path)


def test_the_filename_must_carry_the_id(tmp_path: Path) -> None:
    path = _write(tmp_path, "T-002-a-ticket.md", _ticket("T-001"))
    with pytest.raises(TicketError, match="filename must start"):
        parse_ticket(path)


def test_in_progress_needs_an_owner_and_a_branch(tmp_path: Path) -> None:
    path = _write(
        tmp_path, "T-001-a-ticket.md", _ticket(status="in-progress", extra_meta="owner: x")
    )
    with pytest.raises(TicketError, match="second agent"):
        parse_ticket(path)
    path.write_text(
        _ticket(status="in-progress", extra_meta="owner: x\nbranch: feat/x"), encoding="utf-8"
    )
    assert parse_ticket(path).branch == "feat/x"


def test_in_review_needs_a_pr(tmp_path: Path) -> None:
    path = _write(tmp_path, "T-001-a-ticket.md", _ticket(status="in-review"))
    with pytest.raises(TicketError, match="'pr'"):
        parse_ticket(path)


def test_done_needs_a_pr_and_an_outcome(tmp_path: Path) -> None:
    meta = "pr: https://github.com/o/r/pull/1\nclosed: 2026-09-17"
    path = _write(tmp_path, "T-001-a-ticket.md", _ticket(status="done", extra_meta=meta))
    with pytest.raises(TicketError, match="Outcome"):
        parse_ticket(path)
    path.write_text(_ticket(status="done", extra_meta=meta, outcome="Shipped."), encoding="utf-8")
    assert not parse_ticket(path).is_open


def test_a_ready_ticket_cannot_have_an_open_blocker(tmp_path: Path) -> None:
    _write(tmp_path, "T-001-a-ticket.md", _ticket("T-001"))
    _write(tmp_path, "T-002-b-ticket.md", _ticket("T-002", status="ready").replace("[]", "[T-001]"))
    with pytest.raises(TicketError, match="still blocks it"):
        load_tickets(tmp_path)


def test_a_blocker_must_exist(tmp_path: Path) -> None:
    _write(tmp_path, "T-002-b-ticket.md", _ticket("T-002").replace("[]", "[T-009]"))
    with pytest.raises(TicketError, match="does not exist"):
        load_tickets(tmp_path)


def test_two_in_progress_tickets_cannot_share_a_branch(tmp_path: Path) -> None:
    meta = "owner: a\nbranch: feat/same"
    _write(tmp_path, "T-001-a-ticket.md", _ticket("T-001", status="in-progress", extra_meta=meta))
    _write(tmp_path, "T-002-b-ticket.md", _ticket("T-002", status="in-progress", extra_meta=meta))
    with pytest.raises(TicketError, match="claimed by both"):
        load_tickets(tmp_path)


def test_a_duplicate_id_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "T-001-a-ticket.md", _ticket("T-001"))
    _write(tmp_path, "T-001-b-ticket.md", _ticket("T-001"))
    with pytest.raises(TicketError, match="duplicate"):
        load_tickets(tmp_path)


def test_ready_orders_by_priority_then_id(tmp_path: Path) -> None:
    _write(tmp_path, "T-001-a-ticket.md", _ticket("T-001", status="ready"))
    _write(
        tmp_path,
        "T-002-b-ticket.md",
        _ticket("T-002", status="ready").replace("priority: P2", "priority: P0"),
    )
    _write(tmp_path, "T-003-c-ticket.md", _ticket("T-003"))
    assert [t.id for t in ready(load_tickets(tmp_path))] == ["T-002", "T-001"]


def test_the_index_is_deterministic_and_lists_open_before_closed(tmp_path: Path) -> None:
    meta = "pr: https://github.com/o/r/pull/7\nclosed: 2026-09-17"
    _write(
        tmp_path,
        "T-001-a-ticket.md",
        _ticket("T-001", status="done", extra_meta=meta, outcome="ok"),
    )
    _write(tmp_path, "T-002-b-ticket.md", _ticket("T-002", status="ready"))
    tickets = load_tickets(tmp_path)
    first = render_index(tickets)
    assert first == render_index(list(reversed(tickets)))
    assert first.index("T-002") < first.index("## Closed") < first.index("T-001")
    assert "[7](https://github.com/o/r/pull/7)" in first


def test_a_stale_index_fails_the_check(tmp_path: Path) -> None:
    _write(tmp_path, "T-001-a-ticket.md", _ticket("T-001"))
    with pytest.raises(TicketError, match="stale"):
        check(tmp_path)
    write_index(tmp_path)
    assert [t.id for t in check(tmp_path)] == ["T-001"]
    _write(tmp_path, "T-002-b-ticket.md", _ticket("T-002"))
    with pytest.raises(TicketError, match="stale"):
        check(tmp_path)


def test_next_id_and_the_scaffold_round_trip(tmp_path: Path) -> None:
    _write(tmp_path, "T-004-a-ticket.md", _ticket("T-004"))
    ticket_id = next_id(load_tickets(tmp_path))
    assert ticket_id == "T-005"
    text = new_ticket_text(ticket_id, "Drop the chunks!", phase="1-drive", today=TODAY)
    path = _write(tmp_path, f"{ticket_id}-{slugify('Drop the chunks!')}.md", text)
    assert path.name == "T-005-drop-the-chunks.md"
    # The scaffold is a valid file with empty sections, and empty sections
    # are exactly what the check refuses: a ticket has to be written before
    # it counts.
    with pytest.raises(TicketError, match="wish"):
        parse_ticket(path)


@pytest.mark.parametrize(
    "title",
    [
        "query_spreadsheet: answer from the rows",
        "[urgent] a thing",
        'Say "no" more often',
        "# not a heading",
    ],
)
def test_the_scaffold_survives_a_title_yaml_would_misread(tmp_path: Path, title: str) -> None:
    text = new_ticket_text("T-001", title, phase="1-drive", today=TODAY)
    path = _write(tmp_path, "T-001-x.md", text)
    # The only complaint may be the empty sections -- never a YAML error.
    with pytest.raises(TicketError, match="wish"):
        parse_ticket(path)


def test_new_scaffolds_the_next_id_through_the_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "T-004-a-ticket.md", _ticket("T-004"))
    monkeypatch.setattr("go2.backlog.default_root", lambda: tmp_path)
    result = CliRunner().invoke(
        app, ["backlog", "new", "Drop the chunks: all of them", "--phase", "1-drive"]
    )
    assert result.exit_code == 0, result.output
    created = tmp_path / "tickets" / "T-005-drop-the-chunks-all-of-them.md"
    assert created.exists()
    assert "T-005" in result.output
    with pytest.raises(TicketError, match="wish"):
        parse_ticket(created)


def test_new_refuses_an_unknown_phase_through_the_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "T-004-a-ticket.md", _ticket("T-004"))
    monkeypatch.setattr("go2.backlog.default_root", lambda: tmp_path)
    result = CliRunner().invoke(app, ["backlog", "new", "x", "--phase", "9-nowhere"])
    assert result.exit_code == 2
    assert not list((tmp_path / "tickets").glob("T-005*"))


def test_the_repository_backlog_is_consistent() -> None:
    """The real check, against the committed files. This is what CI runs."""
    tickets = check()
    assert tickets, "the backlog has no tickets"
    assert any(t.id == "T-000" for t in tickets)
