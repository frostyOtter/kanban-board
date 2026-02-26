"""
Simplified Kanban board with an automated coding assistant.

Stages: Backlog → In-Progress → Review → Done

The coding assistant is injected as a plain callable:
    assistant(description: str) -> str

This means you can swap between the mock and the real Claude API
with a single argument — no changes to board logic required.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable

from loguru import logger


# ---------------------------------------------------------------------------
# Domain
# ---------------------------------------------------------------------------


class Stage(str, Enum):
    BACKLOG = "backlog"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"


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

    def __str__(self) -> str:
        snippet_preview = (
            f"\n  snippet: {self.code_snippet[:60]}..." if self.code_snippet else ""
        )
        return f"[{self.id}] {self.title!r} — {self.stage.value}{snippet_preview}"


# ---------------------------------------------------------------------------
# Coding assistants  (plain functions — swap freely)
# ---------------------------------------------------------------------------


def mock_assistant(description: str) -> str:
    """Returns a deterministic placeholder snippet — no network call."""
    logger.debug("Mock assistant generating snippet for: {!r}", description[:60])
    return (
        f"# AUTO-GENERATED PLACEHOLDER\n"
        f"# Task: {description[:80]}\n\n"
        f"def solution():\n"
        f"    # TODO: implement based on task description\n"
        f"    raise NotImplementedError\n"
    )


# ---------------------------------------------------------------------------
# Board
# ---------------------------------------------------------------------------

CodingAssistant = Callable[[str], str]

VALID_TRANSITIONS: dict[Stage, Stage] = {
    Stage.BACKLOG: Stage.IN_PROGRESS,
    Stage.IN_PROGRESS: Stage.REVIEW,
    Stage.REVIEW: Stage.DONE,
}


class KanbanBoard:
    """
    In-memory Kanban board.  Optionally persists state to a JSON file.

    Args:
        assistant:   Any callable (str) -> str.  Defaults to mock_assistant.
        persist_path: If given, board state is saved after every mutation.
    """

    DEFAULT_PERSIST_PATH = Path("board.json")

    def __init__(
        self,
        assistant: CodingAssistant = mock_assistant,
        persist_path: Path | None = DEFAULT_PERSIST_PATH,
    ) -> None:
        self._tasks: dict[str, Task] = {}
        self._assistant = assistant
        self._persist_path = persist_path

        if persist_path and persist_path.exists():
            self._load(persist_path)
            logger.info("Board loaded from {}", persist_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_task(self, title: str, description: str) -> Task:
        task = Task(title=title, description=description)
        self._tasks[task.id] = task
        logger.info("Created task {} → {}", task.id, Stage.BACKLOG.value)
        self._save()
        return task

    def move_to_in_progress(self, task_id: str) -> Task:
        task = self._get(task_id)
        self._assert_stage(task, Stage.BACKLOG)
        task.stage = Stage.IN_PROGRESS
        logger.info("Task {} → {}", task_id, Stage.IN_PROGRESS.value)

        logger.info("Coding assistant is analysing task {}…", task_id)
        task.code_snippet = self._assistant(task.description)
        logger.success("Coding assistant finished for task {}", task_id)

        self._save()
        return task

    def move_to_review(self, task_id: str) -> Task:
        task = self._get(task_id)
        self._assert_stage(task, Stage.IN_PROGRESS)
        task.stage = Stage.REVIEW
        logger.info("Task {} → {}", task_id, Stage.REVIEW.value)
        self._save()
        return task

    def approve(self, task_id: str) -> Task:
        task = self._get(task_id)
        self._assert_stage(task, Stage.REVIEW)
        task.stage = Stage.DONE
        logger.success("Task {} approved → {}", task_id, Stage.DONE.value)
        self._save()
        return task

    def board_view(self) -> None:
        """Prints a simple board snapshot grouped by stage."""
        for stage in Stage:
            tasks = [t for t in self._tasks.values() if t.stage == stage]
            print(f"\n── {stage.value.upper()} ({len(tasks)}) ──")
            for t in tasks:
                print(" ", t)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, task_id: str) -> Task:
        if task_id not in self._tasks:
            raise KeyError(f"Task '{task_id}' not found.")
        return self._tasks[task_id]

    @staticmethod
    def _assert_stage(task: Task, expected: Stage) -> None:
        if task.stage != expected:
            raise ValueError(
                f"Task '{task.id}' is in stage '{task.stage.value}', "
                f"expected '{expected.value}'."
            )

    def _save(self) -> None:
        if not self._persist_path:
            return
        data = {tid: asdict(t) for tid, t in self._tasks.items()}
        self._persist_path.write_text(json.dumps(data, indent=2))
        logger.debug("Board persisted to {}", self._persist_path)

    def _load(self, path: Path) -> None:
        data = json.loads(path.read_text())
        for tid, raw in data.items():
            raw["stage"] = Stage(raw["stage"])
            self._tasks[tid] = Task(**raw)


# ---------------------------------------------------------------------------
# Quick demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Swap `mock_assistant` for `claude_assistant` to use the real API.
    board = KanbanBoard(assistant=mock_assistant)

    # 1. Create tasks
    t1 = board.create_task(
        title="CSV parser",
        description="Write a function that reads a CSV file and returns a list of dicts.",
    )
    t2 = board.create_task(
        title="Rate limiter",
        description="Implement a token-bucket rate limiter for an HTTP client.",
    )

    board.board_view()

    # 2. Pick up first task
    board.move_to_in_progress(t1.id)
    board.board_view()

    # 3. Inspect the generated snippet
    print("\n── Generated snippet for", t1.title, "──")
    print(board._tasks[t1.id].code_snippet)

    # 4. Send to review, then approve
    board.move_to_review(t1.id)
    board.approve(t1.id)

    board.board_view()
