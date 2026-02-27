"""
Hooks system — decouple side effects from board logic.

Board fires events; listeners react. Nothing inside board.py knows or cares
what happens downstream.
"""

from __future__ import annotations

from typing import Callable, Awaitable

from loguru import logger

from .domain import Task


AsyncHookFn = Callable[[Task], Awaitable[None]]


class HookRegistry:
    """Maps event names to lists of async callables."""

    def __init__(self) -> None:
        self._hooks: dict[str, list[AsyncHookFn]] = {
            "on_transition": [],
            "on_done": [],
            "on_stale_task": [],
        }

    def register(self, event: str, hook: AsyncHookFn) -> None:
        if event not in self._hooks:
            raise ValueError(f"Unknown hook event: {event}")
        self._hooks[event].append(hook)

    async def fire(self, event: str, task: Task) -> None:
        for hook in self._hooks.get(event, []):
            try:
                await hook(task)
            except Exception as e:
                logger.error(f"Hook {event} failed: {e}")


async def log_transition(task: Task) -> None:
    """Built-in hook: logs every task transition."""
    logger.info(f"Task {task.id} → {task.stage.value}")
