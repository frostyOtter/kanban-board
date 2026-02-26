"""
Async coding assistants.

An assistant is any async callable with signature:
    async (description: str) -> str

Swap the assistant injected into AsyncKanbanBoard to change behaviour
without touching any board logic.
"""

from __future__ import annotations

import asyncio
from typing import Callable, Coroutine, Any

from loguru import logger


# Type alias used by the board
AsyncCodingAssistant = Callable[[str], Coroutine[Any, Any, str]]


async def async_mock_assistant(description: str) -> str:
    """Simulates network latency — no real API call."""
    logger.debug("Mock assistant: analysing {!r}…", description[:50])
    await asyncio.sleep(0.1)
    return (
        f"# AUTO-GENERATED PLACEHOLDER\n"
        f"# Task: {description[:80]}\n\n"
        f"def solution():\n"
        f"    # TODO: implement based on task description\n"
        f"    raise NotImplementedError\n"
    )


async def async_claude_assistant(description: str) -> str:
    """Calls the real Anthropic async API to generate a code snippet."""
    try:
        from anthropic import AsyncAnthropic
    except ImportError as exc:
        raise RuntimeError(
            "Run `pip install anthropic` to use the real assistant."
        ) from exc

    client = AsyncAnthropic()
    logger.debug("Claude async API: generating snippet…")
    message = await client.messages.create(
        model="claude-opus-4-6",
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": (
                    "You are a coding assistant on a Kanban board.\n"
                    "Generate a minimal Python code snippet (skeleton + docstring) "
                    "for the following task. Return only the code, no explanation.\n\n"
                    f"Task description:\n{description}"
                ),
            }
        ],
    )
    return message.content[0].text
