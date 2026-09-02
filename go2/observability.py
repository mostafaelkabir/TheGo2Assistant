# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Per-component tracing of the retrieval path.

Logs say a request arrived and a response left. They do not say which component
did what to the data in between, so when an answer is wrong there is nothing to
inspect. This records each step: what went in, what came out, how long it took,
and whether it sent anything off the machine.

Inputs and outputs are recorded as summaries and counts, never raw passage
text. A trace log that quietly becomes a second copy of the corpus is a
liability rather than a diagnostic, and it would sit outside the egress
boundary that guards everything else.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from go2.storage.db import connect

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Step:
    """One component's contribution to a request."""

    component: str
    duration_ms: float
    egress: bool = False
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Trace:
    """A single request as it passes through the components.

    Collected in memory and written once at the end, so tracing adds one
    insert per request rather than one per step.
    """

    kind: str
    label: str = ""
    outcome: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    steps: list[Step] = field(default_factory=list)
    duration_ms: float = 0.0

    @contextmanager
    def step(
        self, component: str, *, egress: bool = False, **inputs: object
    ) -> Iterator[dict[str, Any]]:
        """Time one component and record what it produced.

        Yields a dict the caller fills with output facts -- counts, scores,
        decisions -- which are stored as the step's output.

        Args:
            component: Name of the component doing the work.
            egress: Whether this step sends data to a third party.
            inputs: Summary facts about what went in.
        """
        output: dict[str, Any] = {}
        started = time.perf_counter()
        try:
            yield output
        finally:
            self.steps.append(
                Step(
                    component=component,
                    duration_ms=(time.perf_counter() - started) * 1000,
                    egress=egress,
                    input=inputs,
                    output=output,
                )
            )

    def save(self, *, tenant_id: str) -> str | None:
        """Persist the trace.

        Returns:
            The trace id, or ``None`` if writing failed -- tracing must never
            be the reason a query fails, so storage errors are logged and
            swallowed rather than raised.
        """
        try:
            with connect() as conn:
                trace_id = conn.execute(
                    text("""
                        INSERT INTO traces (tenant_id, kind, label, outcome, duration_ms, meta)
                        VALUES (:t, :kind, :label, :outcome, :ms, CAST(:meta AS jsonb))
                        RETURNING id
                    """),
                    {
                        "t": tenant_id,
                        "kind": self.kind,
                        "label": self.label[:200],
                        "outcome": self.outcome,
                        "ms": self.duration_ms or sum(s.duration_ms for s in self.steps),
                        "meta": _json(self.meta),
                    },
                ).scalar_one()

                if self.steps:
                    conn.execute(
                        text("""
                            INSERT INTO trace_steps
                                (trace_id, ordinal, component, duration_ms, egress, input, output)
                            VALUES (:tid, :ord, :c, :ms, :eg,
                                    CAST(:inp AS jsonb), CAST(:out AS jsonb))
                        """),
                        [
                            {
                                "tid": trace_id,
                                "ord": index,
                                "c": step.component,
                                "ms": step.duration_ms,
                                "eg": step.egress,
                                "inp": _json(step.input),
                                "out": _json(step.output),
                            }
                            for index, step in enumerate(self.steps)
                        ],
                    )
            return str(trace_id)
        except Exception as exc:  # noqa: BLE001 -- never fail a query to record it.
            logger.warning("could not save trace: %s", exc)
            return None


def _json(payload: dict[str, Any]) -> str:
    import json  # noqa: PLC0415 -- only needed on the write path.

    return json.dumps(payload, default=str)


def recent(tenant_id: str, *, limit: int = 10, kind: str | None = None) -> list[dict[str, Any]]:
    """Return recent traces with their steps, newest first."""
    clause = "AND kind = :kind" if kind else ""
    with connect() as conn:
        traces = conn.execute(
            text(f"""
                SELECT id, kind, label, outcome, duration_ms, meta, created_at
                  FROM traces WHERE tenant_id = :t {clause}
                 ORDER BY created_at DESC LIMIT :limit
            """),  # noqa: S608 -- `clause` is a fixed string.
            {"t": tenant_id, "limit": limit, **({"kind": kind} if kind else {})},
        ).all()

        out: list[dict[str, Any]] = []
        for trace in traces:
            steps = conn.execute(
                text("""
                    SELECT ordinal, component, duration_ms, egress, input, output
                      FROM trace_steps WHERE trace_id = :id ORDER BY ordinal
                """),
                {"id": trace.id},
            ).all()
            out.append(
                {
                    "id": str(trace.id),
                    "kind": trace.kind,
                    "label": trace.label,
                    "outcome": trace.outcome,
                    "duration_ms": trace.duration_ms,
                    "meta": trace.meta,
                    "created_at": trace.created_at,
                    "steps": [
                        {
                            "component": s.component,
                            "duration_ms": s.duration_ms,
                            "egress": s.egress,
                            "input": s.input,
                            "output": s.output,
                        }
                        for s in steps
                    ],
                }
            )
    return out
