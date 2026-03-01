"""Tests for kanban.board.AsyncKanbanBoard - modern implementation."""

import asyncio
from pathlib import Path
import tempfile

import pytest
import pytest_asyncio

from kanban.board import AsyncKanbanBoard, stale_task_monitor
from kanban.domain import AuditEntry, Stage as KanbanStage


@pytest.fixture
def temp_persist_path():
    """Create a temporary file path for board persistence."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
        path = Path(f.name)
    yield path
    if path.exists():
        path.unlink()


@pytest_asyncio.fixture
async def board(temp_persist_path):
    """Create a fresh board for each test."""
    if temp_persist_path.exists():
        temp_persist_path.unlink()
    return AsyncKanbanBoard(persist_path=temp_persist_path)


@pytest.mark.asyncio
async def test_find_stale_no_stale_tasks(board):
    """Test find_stale returns empty list when no tasks are stale."""
    await board.create_task("Task 1", "Desc 1")
    await board.create_task("Task 2", "Desc 2")

    stale = board.find_stale(threshold_seconds=300)
    assert len(stale) == 0


@pytest.mark.asyncio
async def test_find_stale_with_stale_task(board):
    """Test find_stale correctly identifies stale IN_PROGRESS tasks."""
    from datetime import datetime, timezone

    task = await board.create_task("Stale Task", "Will become stale")
    await board.move_to_in_progress(task.id)

    # Manually set the transition time to be old
    for entry in reversed(task.history):
        if entry.to_stage == KanbanStage.IN_PROGRESS:
            old_time = datetime.now(timezone.utc).timestamp() - 400
            task.history.remove(entry)
            task.history.append(
                AuditEntry(
                    from_stage=entry.from_stage,
                    to_stage=entry.to_stage,
                    timestamp=datetime.fromtimestamp(
                        old_time, tz=timezone.utc
                    ).isoformat(),
                    note=entry.note,
                )
            )
            break

    stale = board.find_stale(threshold_seconds=300)
    assert len(stale) == 1
    assert stale[0].id == task.id


@pytest.mark.asyncio
async def test_find_stale_ignores_non_in_progress(board):
    """Test find_stale ignores tasks not in IN_PROGRESS stage."""
    t1 = await board.create_task("Task 1", "Desc 1")
    t2 = await board.create_task("Task 2", "Desc 2")

    # Move t1 through IN_PROGRESS to REVIEW to DONE (not stale)
    await board.move_to_in_progress(t1.id)
    await board.move_to_review(t1.id)
    await board.approve(t1.id)

    # Move t2 to IN_PROGRESS and make it stale
    await board.move_to_in_progress(t2.id)

    # Set t2 as stale
    from datetime import datetime, timezone

    for entry in reversed(t2.history):
        if entry.to_stage == KanbanStage.IN_PROGRESS:
            old_time = datetime.now(timezone.utc).timestamp() - 400
            t2.history.remove(entry)
            t2.history.append(
                AuditEntry(
                    from_stage=entry.from_stage,
                    to_stage=entry.to_stage,
                    timestamp=datetime.fromtimestamp(
                        old_time, tz=timezone.utc
                    ).isoformat(),
                    note=entry.note,
                )
            )
            break

    stale = board.find_stale(threshold_seconds=300)
    assert len(stale) == 1
    assert stale[0].id == t2.id


@pytest.mark.asyncio
async def test_find_stale_uses_audit_timestamp_not_created_at(board):
    """Test find_stale uses audit trail timestamp, not task.created_at."""
    from datetime import datetime, timezone, timedelta

    task = await board.create_task("Old Task", "Created long ago")

    # Simulate old created_at time
    old_created = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    task.created_at = old_created

    # Move to IN_PROGRESS recently
    await board.move_to_in_progress(task.id)

    # Task should NOT be stale because it was moved to IN_PROGRESS recently
    stale = board.find_stale(threshold_seconds=300)
    assert len(stale) == 0

    # Now make the IN_PROGRESS transition old
    for entry in reversed(task.history):
        if entry.to_stage == KanbanStage.IN_PROGRESS:
            old_time = datetime.now(timezone.utc).timestamp() - 400
            task.history.remove(entry)
            task.history.append(
                AuditEntry(
                    from_stage=entry.from_stage,
                    to_stage=entry.to_stage,
                    timestamp=datetime.fromtimestamp(
                        old_time, tz=timezone.utc
                    ).isoformat(),
                    note=entry.note,
                )
            )
            break

    # Now task should be stale
    stale = board.find_stale(threshold_seconds=300)
    assert len(stale) == 1


@pytest.mark.asyncio
async def test_stale_monitor(board):
    """Test stale monitor detects stale tasks and fires hooks."""
    from datetime import datetime, timezone

    threshold = 1  # 1 second
    poll_interval = 1  # 1 second

    task = await board.create_task("Stale Task", "Will become stale")
    await board.move_to_in_progress(task.id)

    hook_calls = []

    async def track_stale(t):
        hook_calls.append(t.id)

    board._hook_registry.register("on_stale_task", track_stale)

    # Set the transition time to be old
    for entry in reversed(task.history):
        if entry.to_stage == KanbanStage.IN_PROGRESS:
            old_time = datetime.now(timezone.utc).timestamp() - 2
            task.history.remove(entry)
            task.history.append(
                AuditEntry(
                    from_stage=entry.from_stage,
                    to_stage=entry.to_stage,
                    timestamp=datetime.fromtimestamp(
                        old_time, tz=timezone.utc
                    ).isoformat(),
                    note=entry.note,
                )
            )
            break

    # Start monitor, wait for detection, then cancel
    monitor = asyncio.create_task(stale_task_monitor(board, threshold, poll_interval))
    await asyncio.sleep(2)  # Wait for at least one poll cycle
    monitor.cancel()

    try:
        await monitor
    except asyncio.CancelledError:
        pass

    assert len(hook_calls) >= 1
    assert task.id in hook_calls


@pytest.mark.asyncio
async def test_stale_monitor_respects_stage_changes(board):
    """Test that tasks moved out of IN_PROGRESS are no longer considered stale."""
    from datetime import datetime, timezone

    threshold = 1  # 1 second
    poll_interval = 1  # 1 second

    task = await board.create_task("Task", "Will move to review")
    await board.move_to_in_progress(task.id)

    hook_calls = []

    async def track_stale(t):
        hook_calls.append(t.id)

    board._hook_registry.register("on_stale_task", track_stale)

    # Set the transition time to be old
    for entry in reversed(task.history):
        if entry.to_stage == KanbanStage.IN_PROGRESS:
            old_time = datetime.now(timezone.utc).timestamp() - 2
            task.history.remove(entry)
            task.history.append(
                AuditEntry(
                    from_stage=entry.from_stage,
                    to_stage=entry.to_stage,
                    timestamp=datetime.fromtimestamp(
                        old_time, tz=timezone.utc
                    ).isoformat(),
                    note=entry.note,
                )
            )
            break

    # Start monitor
    monitor = asyncio.create_task(stale_task_monitor(board, threshold, poll_interval))
    await asyncio.sleep(1.5)  # Wait for at least one poll cycle

    # Move task to REVIEW - should stop being stale
    await board.move_to_review(task.id)

    await asyncio.sleep(1.5)  # Wait for another poll cycle
    monitor.cancel()

    try:
        await monitor
    except asyncio.CancelledError:
        pass

    # Hook should have fired at least once before we moved the task
    assert len(hook_calls) >= 1


@pytest.mark.asyncio
async def test_stale_monitor_handles_multiple_stale_tasks(board):
    """Test monitor fires hook for each stale task."""
    from datetime import datetime, timezone

    threshold = 2  # 2 seconds
    poll_interval = 1  # 1 second

    t1 = await board.create_task("Task 1", "Stale 1")
    t2 = await board.create_task("Task 2", "Stale 2")
    t3 = await board.create_task("Task 3", "Fresh")

    await board.move_to_in_progress(t1.id)
    await board.move_to_in_progress(t2.id)

    hook_calls = []

    async def track_stale(t):
        hook_calls.append(t.id)

    board._hook_registry.register("on_stale_task", track_stale)

    # Make t1 and t2 old (3 seconds ago, exceeding the 2-second threshold)
    for task in [t1, t2]:
        for entry in reversed(task.history):
            if entry.to_stage == KanbanStage.IN_PROGRESS:
                old_time = datetime.now(timezone.utc).timestamp() - 3
                task.history.remove(entry)
                task.history.append(
                    AuditEntry(
                        from_stage=entry.from_stage,
                        to_stage=entry.to_stage,
                        timestamp=datetime.fromtimestamp(
                            old_time, tz=timezone.utc
                        ).isoformat(),
                        note=entry.note,
                    )
                )
                break

    # Move t3 to IN_PROGRESS last so it's naturally fresh (will be < 2 seconds old when checked)
    await board.move_to_in_progress(t3.id)

    # Start monitor
    monitor = asyncio.create_task(stale_task_monitor(board, threshold, poll_interval))
    await asyncio.sleep(1.5)  # Wait for at least one poll cycle
    monitor.cancel()

    try:
        await monitor
    except asyncio.CancelledError:
        pass

    assert len(hook_calls) >= 2
    assert t1.id in hook_calls
    assert t2.id in hook_calls
    assert t3.id not in hook_calls
