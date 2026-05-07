"""
Metrics schema for evaluating the agentic system.

Two key metrics:
  TSR  — Task Success Rate: percentage of agent tasks that completed successfully
  MTTR — Mean Time To Resolution: average wall-clock seconds from task start to completion

Events are written to metrics/events.json and computed by calculate.py.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Task types the system handles
# ---------------------------------------------------------------------------

TASK_TYPES = [
    "security-analysis",      # PR diff analysed by Foundation-Sec-8B / Claude
    "kg-extraction",          # knowledge graph updated from source files
    "kg-query",               # question answered from knowledge graph
    "change-impact",          # blast radius analysis for a proposed change
    "infra-advisory",         # conversational infra advice session
    "ci-pipeline",            # end-to-end CI: test → build → push → deploy
    "gitops-sync",            # ArgoCD sync event
]


# ---------------------------------------------------------------------------
# Event schema
# ---------------------------------------------------------------------------

@dataclass
class TaskEvent:
    task_type: str
    description: str
    success: bool
    started_at: str        # ISO-8601 UTC
    completed_at: str      # ISO-8601 UTC
    duration_s: float      # completed_at - started_at in seconds
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        task_type: str,
        description: str,
        success: bool,
        started_at: datetime,
        completed_at: datetime,
        error: str | None = None,
        metadata: dict | None = None,
    ) -> "TaskEvent":
        duration = (completed_at - started_at).total_seconds()
        return cls(
            task_type=task_type,
            description=description,
            success=success,
            started_at=started_at.isoformat(),
            completed_at=completed_at.isoformat(),
            duration_s=round(duration, 2),
            error=error,
            metadata=metadata or {},
        )

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Event log (thin wrapper over events.json)
# ---------------------------------------------------------------------------

EVENTS_PATH = Path(__file__).parent / "events.json"


def load_events(path: Path = EVENTS_PATH) -> list[TaskEvent]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    return [TaskEvent(**e) for e in raw.get("events", [])]


def append_event(event: TaskEvent, path: Path = EVENTS_PATH) -> None:
    events = load_events(path)
    events.append(event)
    path.write_text(
        json.dumps(
            {"events": [e.to_dict() for e in events]},
            indent=2,
        )
    )


def log_event(
    task_type: str,
    description: str,
    success: bool,
    started_at: datetime,
    completed_at: datetime | None = None,
    error: str | None = None,
    metadata: dict | None = None,
    path: Path = EVENTS_PATH,
) -> TaskEvent:
    """Convenience function: create and append an event in one call."""
    if completed_at is None:
        completed_at = datetime.now(timezone.utc)
    event = TaskEvent.create(
        task_type=task_type,
        description=description,
        success=success,
        started_at=started_at,
        completed_at=completed_at,
        error=error,
        metadata=metadata,
    )
    append_event(event, path)
    return event
