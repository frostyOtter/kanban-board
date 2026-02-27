"""
Core domain: Task, Stage, AuditEntry, and all board-specific exceptions.

Nothing here imports from the rest of the package — this is the
innermost layer and has zero side-effects.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


# ---------------------------------------------------------------------------
# Stage
# ---------------------------------------------------------------------------


class Stage(str, Enum):
    BACKLOG = "backlog"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"


# ---------------------------------------------------------------------------
# AuditEntry
# ---------------------------------------------------------------------------


@dataclass
class AuditEntry:
    """A single immutable record of a stage transition."""

    from_stage: Stage | None  # None for the initial "created" entry
    to_stage: Stage
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    note: str | None = None  # optional free-text reason

    def __str__(self) -> str:
        arrow = f"{self.from_stage.value} → " if self.from_stage else ""
        note_str = f" ({self.note})" if self.note else ""
        return f"[{self.timestamp}] {arrow}{self.to_stage.value}{note_str}"


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


@dataclass
class Task:
    title: str
    description: str
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    stage: Stage = Stage.BACKLOG
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    code_snippet: str | None = None
    depends_on: list[str] = field(default_factory=list)  # list of Task.id
    history: list[AuditEntry] = field(default_factory=list)  # audit log
    review_notes: str | None = None

    def __str__(self) -> str:
        deps = f" deps={self.depends_on}" if self.depends_on else ""
        preview = (
            f"\n    snippet: {self.code_snippet[:60]}…" if self.code_snippet else ""
        )
        return f"[{self.id}] {self.title!r} — {self.stage.value}{deps}{preview}"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BoardError(Exception):
    """Base for all board-specific errors."""


class TaskNotFoundError(BoardError):
    def __init__(self, task_id: str) -> None:
        super().__init__(f"Task '{task_id}' not found.")
        self.task_id = task_id


class InvalidTransitionError(BoardError):
    def __init__(self, task_id: str, current: Stage, expected: Stage) -> None:
        super().__init__(
            f"Task '{task_id}' is in '{current.value}', expected '{expected.value}'."
        )
        self.task_id = task_id
        self.current = current
        self.expected = expected


class WIPLimitError(BoardError):
    def __init__(self, current: int, limit: int) -> None:
        super().__init__(
            f"WIP limit reached ({current}/{limit}). "
            "Finish or review a task before starting a new one."
        )
        self.current = current
        self.limit = limit


class UnresolvedDependencyError(BoardError):
    """Raised when a task has dependencies that are not yet Done."""

    def __init__(self, task_id: str, blocking: list[str]) -> None:
        super().__init__(
            f"Task '{task_id}' is blocked by unfinished dependencies: {blocking}."
        )
        self.task_id = task_id
        self.blocking = blocking
