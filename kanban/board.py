"""
AsyncKanbanBoard — core board logic.

Responsibilities:
  - CRUD for tasks
  - Stage transition enforcement (Backlog → In-Progress → Review → Done)
  - Reject transition (Review → Backlog) with retry tracking
  - WIP limit (max concurrent In-Progress tasks)
  - Dependency resolution (hard-block on unfinished deps)
  - JSON persistence (sync, fine at this scale)

The board is the only place that mutates task state. All public methods
are async and protected by a single asyncio.Lock.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from loguru import logger

from .assistants import (
    AsyncCodingAssistant,
    AsyncReviewerAssistant,
    async_mock_assistant,
)
from .domain import (
    AuditEntry,
    InvalidTransitionError,
    Stage,
    Task,
    TaskNotFoundError,
    UnresolvedDependencyError,
    WIPLimitError,
)
from .hooks import AsyncHookFn, HookRegistry

import asyncio


class AsyncKanbanBoard:
    """
    Args:
        assistant:    Any async callable ``(str) -> str``.
        wip_limit:    Max tasks allowed in In-Progress simultaneously.
        persist_path: If given, board state is saved after every mutation.
                      Pass ``None`` to disable persistence (useful in tests).
    """

    DEFAULT_PERSIST_PATH = Path("board.json")

    def __init__(
        self,
        assistant: AsyncCodingAssistant = async_mock_assistant,
        wip_limit: int = 3,
        persist_path: Path | None = DEFAULT_PERSIST_PATH,
        hooks: dict[str, list[AsyncHookFn]] | None = None,
        reviewer: AsyncReviewerAssistant | None = None,
    ) -> None:
        self._tasks: dict[str, Task] = {}
        self._assistant = assistant
        self._wip_limit = wip_limit
        self._persist_path = persist_path
        self._lock = asyncio.Lock()
        self._hook_registry = HookRegistry()
        self._reviewer = reviewer
        if hooks:
            for event, hook_list in hooks.items():
                for hook in hook_list:
                    self._hook_registry.register(event, hook)

        if persist_path and persist_path.exists():
            self._load(persist_path)
            logger.info("Board loaded from {}", persist_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_task(
        self,
        title: str,
        description: str,
        depends_on: list[str] | None = None,
    ) -> Task:
        """
        Create a new task in Backlog.

        Args:
            depends_on: IDs of tasks that must reach Done before this
                        task can move to In-Progress.

        Raises:
            TaskNotFoundError: If any dependency ID does not exist.
        """
        deps = depends_on or []
        async with self._lock:
            # Validate all dependency IDs exist before creating the task
            for dep_id in deps:
                if dep_id not in self._tasks:
                    raise TaskNotFoundError(dep_id)
            task = Task(title=title, description=description, depends_on=deps)
            self._record(task, from_stage=None, to_stage=Stage.BACKLOG, note="created")
            self._tasks[task.id] = task
            self._save()

        dep_info = f" (depends on {deps})" if deps else ""
        logger.info("Created  {} — {!r}{}", task.id, title, dep_info)
        await self._fire_hook("on_transition", task)
        return task

    async def move_to_in_progress(self, task_id: str) -> Task:
        """
        Move a Backlog task to In-Progress, then run the coding assistant.

        Raises:
            TaskNotFoundError:         Task does not exist.
            InvalidTransitionError:    Task is not in Backlog.
            WIPLimitError:             In-Progress count would exceed wip_limit.
            UnresolvedDependencyError: One or more dependencies are not Done.
        """
        async with self._lock:
            task = self._get(task_id)
            self._assert_stage(task, Stage.BACKLOG)
            self._check_dependencies(task)

            wip_count = self._count_stage(Stage.IN_PROGRESS)
            if wip_count >= self._wip_limit:
                raise WIPLimitError(current=wip_count, limit=self._wip_limit)

            # Commit stage immediately so concurrent callers see the updated count
            task.stage = Stage.IN_PROGRESS
            self._record(task, from_stage=Stage.BACKLOG, to_stage=Stage.IN_PROGRESS)
            self._save()

        logger.info(
            "Task {}  →  in_progress  (wip {}/{})",
            task_id,
            wip_count + 1,
            self._wip_limit,
        )

        # Run assistant OUTSIDE the lock — pure I/O, no shared state mutation
        logger.info("Coding assistant analysing task {}…", task_id)
        snippet = await self._assistant(task.description)

        async with self._lock:
            task.code_snippet = snippet
            self._save()

        logger.success("Coding assistant done for task {}", task_id)
        await self._fire_hook("on_transition", task)
        return task

    async def move_to_review(self, task_id: str) -> Task:
        async with self._lock:
            task = self._get(task_id)
            self._assert_stage(task, Stage.IN_PROGRESS)
            task.stage = Stage.REVIEW
            self._record(task, from_stage=Stage.IN_PROGRESS, to_stage=Stage.REVIEW)
            self._save()

        await self._fire_hook("on_transition", task)

        if self._reviewer:
            logger.info("Reviewer analysing task {}…", task_id)
            notes = await self._reviewer(task.description, task.code_snippet or "")

            async with self._lock:
                task.review_notes = notes
                self._save()

            logger.success("Reviewer done for task {}", task_id)

        return task

    async def approve(self, task_id: str) -> Task:
        async with self._lock:
            task = self._get(task_id)
            self._assert_stage(task, Stage.REVIEW)
            task.stage = Stage.DONE
            self._record(task, from_stage=Stage.REVIEW, to_stage=Stage.DONE)
            self._save()
        logger.success("Task {}  →  done  ✓", task_id)
        await self._fire_hook("on_transition", task)
        await self._fire_hook("on_done", task)
        return task

    async def reject(self, task_id: str, reason: str) -> Task:
        """
        Reject a task from REVIEW, returning it to BACKLOG.

        Args:
            task_id: ID of task to reject.
            reason: Free-text reason for rejection (stored in audit trail).

        Returns:
            The updated task with stage=BACKLOG and incremented retry_count.

        Raises:
            TaskNotFoundError:      Task does not exist.
            InvalidTransitionError: Task is not in REVIEW stage.
        """
        async with self._lock:
            task = self._get(task_id)
            self._assert_stage(task, Stage.REVIEW)
            task.stage = Stage.BACKLOG
            task.retry_count += 1
            self._record(
                task, from_stage=Stage.REVIEW, to_stage=Stage.BACKLOG, note=reason
            )
            self._save()

        logger.info("Task {} rejected → backlog (reason: {})", task_id, reason[:50])
        await self._fire_hook("on_rejected", task)
        return task

    def get_task(self, task_id: str) -> Task:
        """Synchronous read — safe to call from routes without await."""
        return self._get(task_id)

    def all_tasks(self) -> list[Task]:
        return list(self._tasks.values())

    def tasks_by_stage(self, stage: Stage) -> list[Task]:
        return [t for t in self._tasks.values() if t.stage == stage]

    def board_view(self) -> None:
        """Prints a snapshot grouped by stage."""
        for stage in Stage:
            tasks = self.tasks_by_stage(stage)
            cap = f"{self._wip_limit}" if stage == Stage.IN_PROGRESS else "∞"
            print(f"\n── {stage.value.upper()} ({len(tasks)}/{cap}) ──")
            for t in tasks:
                print(" ", t)

    def find_stale(self, threshold_seconds: int = 300) -> list[Task]:
        """
        Find tasks stuck in IN_PROGRESS longer than threshold.

        Args:
            threshold_seconds: Maximum seconds allowed in IN_PROGRESS (default: 300).

        Returns:
            List of tasks that have been in IN_PROGRESS longer than threshold.
        """
        from datetime import datetime, timezone

        cutoff = datetime.now(timezone.utc).timestamp() - threshold_seconds
        stale = []

        for task in self._tasks.values():
            if task.stage != Stage.IN_PROGRESS:
                continue

            # Find the most recent transition to IN_PROGRESS
            transition_time = None
            for entry in reversed(task.history):
                if entry.to_stage == Stage.IN_PROGRESS:
                    transition_time = datetime.fromisoformat(
                        entry.timestamp
                    ).timestamp()
                    break

            if transition_time and transition_time < cutoff:
                stale.append(task)

        return stale

    async def _fire_hook(self, event: str, task: Task) -> None:
        """Fire hooks for the given event. Errors are caught and logged."""
        await self._hook_registry.fire(event, task)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record(
        self,
        task: Task,
        from_stage: Stage | None,
        to_stage: Stage,
        note: str | None = None,
    ) -> None:
        """Append an AuditEntry to the task's history. Must be called inside the lock."""
        entry = AuditEntry(from_stage=from_stage, to_stage=to_stage, note=note)
        task.history.append(entry)
        logger.debug("Audit [{}] {} → {}", task.id, from_stage, to_stage)

    def _get(self, task_id: str) -> Task:
        if task_id not in self._tasks:
            raise TaskNotFoundError(task_id)
        return self._tasks[task_id]

    def _count_stage(self, stage: Stage) -> int:
        return sum(1 for t in self._tasks.values() if t.stage == stage)

    @staticmethod
    def _assert_stage(task: Task, expected: Stage) -> None:
        if task.stage != expected:
            raise InvalidTransitionError(task.id, task.stage, expected)

    def _check_dependencies(self, task: Task) -> None:
        """Raises UnresolvedDependencyError if any dependency is not Done."""
        blocking = [
            dep_id
            for dep_id in task.depends_on
            if dep_id in self._tasks and self._tasks[dep_id].stage != Stage.DONE
        ]
        if blocking:
            raise UnresolvedDependencyError(task.id, blocking)

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
            raw["history"] = [
                AuditEntry(
                    from_stage=Stage(e["from_stage"]) if e["from_stage"] else None,
                    to_stage=Stage(e["to_stage"]),
                    timestamp=e["timestamp"],
                    note=e.get("note"),
                )
                for e in raw.get("history", [])
            ]
            raw["review_notes"] = raw.get("review_notes")
            raw["retry_count"] = raw.get("retry_count", 0)
            self._tasks[tid] = Task(**raw)


async def stale_task_monitor(
    board: "AsyncKanbanBoard",
    threshold_seconds: int = 300,
    poll_interval_seconds: int = 60,
) -> None:
    """
    Background task that polls for stale tasks and fires on_stale_task hooks.

    Args:
        board: The AsyncKanbanBoard instance to monitor.
        threshold_seconds: Maximum seconds allowed in IN_PROGRESS (default: 300).
        poll_interval_seconds: How often to poll for stale tasks (default: 60).

    Raises:
        asyncio.CancelledError: When the monitor is cancelled during shutdown.
    """
    logger.info(
        "Stale task monitor started (threshold: {}s, poll: {}s)",
        threshold_seconds,
        poll_interval_seconds,
    )

    try:
        while True:
            await asyncio.sleep(poll_interval_seconds)
            stale = board.find_stale(threshold_seconds)

            if stale:
                logger.warning("Found {} stale tasks", len(stale))
                for task in stale:
                    await board._fire_hook("on_stale_task", task)
    except asyncio.CancelledError:
        logger.info("Stale task monitor shutting down...")
        raise
    except Exception as e:
        logger.error("Stale task monitor crashed: {}", e)
