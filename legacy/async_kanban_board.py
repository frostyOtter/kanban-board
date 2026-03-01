"""
Async Kanban board with WIP limit and concurrent coding-assistant calls.

Stages: Backlog → In-Progress → Review → Done

Changes from v1 (kanban.py):
  - All board mutations are now `async def` — safe to call with asyncio.gather().
  - The coding assistant is `AsyncCodingAssistant`: async (str) -> str.
  - WIP limit is enforced on move_to_in_progress(); raises WIPLimitError when
    the number of In-Progress tasks would exceed the cap.
  - Persistence (_save / _load) stays synchronous — file I/O at this scale
    does not warrant the complexity of aiofiles.

Swapping assistants:
    board = AsyncKanbanBoard(assistant=async_mock_assistant)   # default
    board = AsyncKanbanBoard(assistant=async_claude_assistant) # real API
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Coroutine, Any

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
        preview = (
            f"\n    snippet: {self.code_snippet[:60]}…" if self.code_snippet else ""
        )
        return f"[{self.id}] {self.title!r} — {self.stage.value}{preview}"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class WIPLimitError(Exception):
    """Raised when moving a task to In-Progress would exceed the WIP limit."""


class InvalidTransitionError(Exception):
    """Raised when a stage transition is not allowed."""


# ---------------------------------------------------------------------------
# Async coding assistants
# ---------------------------------------------------------------------------


async def async_mock_assistant(description: str) -> str:
    """Simulates network latency with a short sleep — no real API call."""
    logger.debug("Mock assistant: analysing {!r}…", description[:50])
    await asyncio.sleep(0.1)  # simulate I/O
    return (
        f"# AUTO-GENERATED PLACEHOLDER\n"
        f"# Task: {description[:80]}\n\n"
        f"def solution():\n"
        f"    # TODO: implement based on task description\n"
        f"    raise NotImplementedError\n"
    )


# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

AsyncCodingAssistant = Callable[[str], Coroutine[Any, Any, str]]


# ---------------------------------------------------------------------------
# Async board
# ---------------------------------------------------------------------------


class AsyncKanbanBoard:
    """
    Async Kanban board with WIP limit.

    Args:
        assistant:    Any async callable (str) -> str.
        wip_limit:    Max tasks allowed in In-Progress simultaneously.
        persist_path: If given, board state is saved after every mutation.
    """

    DEFAULT_PERSIST_PATH = Path("board.json")

    def __init__(
        self,
        assistant: AsyncCodingAssistant = async_mock_assistant,
        wip_limit: int = 3,
        persist_path: Path | None = DEFAULT_PERSIST_PATH,
    ) -> None:
        self._tasks: dict[str, Task] = {}
        self._assistant = assistant
        self._wip_limit = wip_limit
        self._persist_path = persist_path
        # Protects _tasks dict from concurrent mutations
        self._lock = asyncio.Lock()

        if persist_path and persist_path.exists():
            self._load(persist_path)
            logger.info("Board loaded from {}", persist_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_task(self, title: str, description: str) -> Task:
        task = Task(title=title, description=description)
        async with self._lock:
            self._tasks[task.id] = task
            self._save()
        logger.info("Created  {} — {!r}", task.id, title)
        return task

    async def move_to_in_progress(self, task_id: str) -> Task:
        async with self._lock:
            task = self._get(task_id)
            self._assert_stage(task, Stage.BACKLOG)
            wip_count = self._count_stage(Stage.IN_PROGRESS)
            if wip_count >= self._wip_limit:
                raise WIPLimitError(
                    f"WIP limit reached ({wip_count}/{self._wip_limit}). "
                    f"Finish or review a task before starting a new one."
                )
            # Mark in-progress immediately so concurrent callers see the updated count
            task.stage = Stage.IN_PROGRESS
            self._save()

        logger.info(
            "Task {}  →  in_progress  (wip {}/{})",
            task_id,
            wip_count + 1,
            self._wip_limit,
        )

        # Run assistant OUTSIDE the lock — it's pure I/O, no shared state mutation
        logger.info("Coding assistant analysing task {}…", task_id)
        snippet = await self._assistant(task.description)

        async with self._lock:
            task.code_snippet = snippet
            self._save()

        logger.success("Coding assistant done for task {}", task_id)
        return task

    async def move_to_review(self, task_id: str) -> Task:
        async with self._lock:
            task = self._get(task_id)
            self._assert_stage(task, Stage.IN_PROGRESS)
            task.stage = Stage.REVIEW
            self._save()
        logger.info("Task {}  →  review", task_id)
        return task

    async def approve(self, task_id: str) -> Task:
        async with self._lock:
            task = self._get(task_id)
            self._assert_stage(task, Stage.REVIEW)
            task.stage = Stage.DONE
            self._save()
        logger.success("Task {}  →  done  ✓", task_id)
        return task

    def board_view(self) -> None:
        """Prints a board snapshot grouped by stage. Sync — safe to call anywhere."""
        for stage in Stage:
            tasks = [t for t in self._tasks.values() if t.stage == stage]
            print(
                f"\n── {stage.value.upper()} ({len(tasks)}/{self._wip_limit if stage == Stage.IN_PROGRESS else '∞'}) ──"
            )
            for t in tasks:
                print(" ", t)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, task_id: str) -> Task:
        if task_id not in self._tasks:
            raise KeyError(f"Task '{task_id}' not found.")
        return self._tasks[task_id]

    def _count_stage(self, stage: Stage) -> int:
        return sum(1 for t in self._tasks.values() if t.stage == stage)

    @staticmethod
    def _assert_stage(task: Task, expected: Stage) -> None:
        if task.stage != expected:
            raise InvalidTransitionError(
                f"Task '{task.id}' is in '{task.stage.value}', expected '{expected.value}'."
            )

    def _save(self) -> None:
        if not self._persist_path:
            return
        data = {tid: asdict(t) for tid, t in self._tasks.items()}
        self._persist_path.write_text(json.dumps(data, indent=2))
        logger.debug("Persisted → {}", self._persist_path)

    def _load(self, path: Path) -> None:
        data = json.loads(path.read_text())
        for tid, raw in data.items():
            raw["stage"] = Stage(raw["stage"])
            self._tasks[tid] = Task(**raw)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


async def main() -> None:
    board = AsyncKanbanBoard(wip_limit=2)  # cap at 2 concurrent tasks

    # 1. Populate backlog
    tasks = await asyncio.gather(
        board.create_task("CSV parser", "Parse a CSV file into a list of dicts."),
        board.create_task("Rate limiter", "Token-bucket rate limiter for HTTP client."),
        board.create_task("Auth module", "JWT-based authentication middleware."),
    )
    t1, t2, t3 = tasks
    board.board_view()

    # 2. Start two tasks concurrently — assistant calls run in parallel
    print("\n── Starting t1 and t2 concurrently ──")
    await asyncio.gather(
        board.move_to_in_progress(t1.id),
        board.move_to_in_progress(t2.id),
    )
    board.board_view()

    # 3. Attempting a third should raise WIPLimitError
    print("\n── Attempting to start t3 (should hit WIP limit) ──")
    try:
        await board.move_to_in_progress(t3.id)
    except WIPLimitError as e:
        logger.warning("Blocked: {}", e)

    # 4. Finish t1 → opens a slot for t3
    await board.move_to_review(t1.id)
    await board.approve(t1.id)
    board.board_view()

    # 5. Now t3 can proceed
    print("\n── Starting t3 after slot freed ──")
    await board.move_to_in_progress(t3.id)
    board.board_view()


if __name__ == "__main__":
    asyncio.run(main())
