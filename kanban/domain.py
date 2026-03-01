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
    """
    Represents a task in the kanban board.

    Attributes:
        title: Human-readable title of the task.
        description: Detailed description of what needs to be done.
        id: Unique identifier (8-character UUID prefix).
        stage: Current stage (BACKLOG, IN_PROGRESS, REVIEW, DONE).
        created_at: ISO timestamp when task was created.
        code_snippet: Generated code snippet (set by coding assistant).
        depends_on: List of task IDs that must be DONE before this task can start.
        history: Audit log of all stage transitions.
        review_notes: Reviewer feedback (set by reviewer assistant).
        retry_count: Number of times task has been rejected from REVIEW.
    """

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
    retry_count: int = 0

    def __str__(self) -> str:
        deps = f" deps={self.depends_on}" if self.depends_on else ""
        retry = f" retry={self.retry_count}" if self.retry_count > 0 else ""
        preview = (
            f"\n    snippet: {self.code_snippet[:60]}…" if self.code_snippet else ""
        )
        return f"[{self.id}] {self.title!r} — {self.stage.value}{deps}{retry}{preview}"


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
