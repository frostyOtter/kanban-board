"""Tests for the hooks system."""

import asyncio
from pathlib import Path
import tempfile

import pytest

from kanban.board import AsyncKanbanBoard
from kanban.domain import Stage
from kanban.hooks import HookRegistry, AsyncHookFn, log_transition


@pytest.fixture
def temp_persist_path():
    """Create a temporary file path for board persistence."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
        path = Path(f.name)
    yield path
    if path.exists():
        path.unlink()


@pytest.fixture
async def board(temp_persist_path):
    """Create a fresh board for each test."""
    if temp_persist_path.exists():
        temp_persist_path.unlink()
    return AsyncKanbanBoard(persist_path=temp_persist_path)


@pytest.mark.asyncio
async def test_hook_registry_initialization():
    """Test HookRegistry initializes with correct events."""
    registry = HookRegistry()
    assert "on_transition" in registry._hooks
    assert "on_done" in registry._hooks
    assert "on_stale_task" in registry._hooks


@pytest.mark.asyncio
async def test_hook_register():
    """Test registering a hook."""
    registry = HookRegistry()

    async def my_hook(task):
        pass

    registry.register("on_transition", my_hook)
    assert my_hook in registry._hooks["on_transition"]


@pytest.mark.asyncio
async def test_hook_register_invalid_event():
    """Test registering a hook with invalid event raises ValueError."""
    registry = HookRegistry()

    async def my_hook(task):
        pass

    with pytest.raises(ValueError, match="Unknown hook event"):
        registry.register("invalid_event", my_hook)


@pytest.mark.asyncio
async def test_hook_fire():
    """Test firing a hook calls the registered function."""
    registry = HookRegistry()

    call_count = []

    async def my_hook(task):
        call_count.append(task.id)

    registry.register("on_transition", my_hook)

    from kanban.domain import Task

    task = Task(title="Test", description="Test")
    await registry.fire("on_transition", task)

    assert len(call_count) == 1
    assert call_count[0] == task.id


@pytest.mark.asyncio
async def test_hook_error_does_not_crash():
    """Test that a hook error is caught and logged, not raised."""
    registry = HookRegistry()

    async def failing_hook(task):
        raise RuntimeError("Hook failed!")

    async def working_hook(task):
        pass

    registry.register("on_transition", failing_hook)
    registry.register("on_transition", working_hook)

    from kanban.domain import Task

    task = Task(title="Test", description="Test")

    # Should not raise
    await registry.fire("on_transition", task)


@pytest.mark.asyncio
async def test_board_accepts_hooks_at_init():
    """Test that board accepts hooks parameter at initialization."""
    call_count = []

    async def my_hook(task):
        call_count.append(task.stage)

    hooks = {"on_transition": [my_hook]}
    board = AsyncKanbanBoard(persist_path=None, hooks=hooks)

    task = await board.create_task("Test", "Desc")
    await asyncio.sleep(0.01)  # Allow hook to execute

    assert len(call_count) == 1
    assert call_count[0] == Stage.BACKLOG


@pytest.mark.asyncio
async def test_on_transition_fired_on_create_task():
    """Test that on_transition is fired when task is created."""
    call_count = []

    async def my_hook(task):
        call_count.append(task.stage)

    hooks = {"on_transition": [my_hook]}
    board = AsyncKanbanBoard(persist_path=None, hooks=hooks)

    await board.create_task("Test", "Desc")
    await asyncio.sleep(0.01)  # Allow hook to execute

    assert len(call_count) == 1
    assert call_count[0] == Stage.BACKLOG


@pytest.mark.asyncio
async def test_on_transition_fired_on_move_to_in_progress():
    """Test that on_transition is fired when task moves to in_progress."""
    call_count = []

    async def my_hook(task):
        call_count.append(task.stage)

    hooks = {"on_transition": [my_hook]}
    board = AsyncKanbanBoard(persist_path=None, hooks=hooks)

    task = await board.create_task("Test", "Desc")
    call_count.clear()  # Clear the create hook call

    await board.move_to_in_progress(task.id)
    await asyncio.sleep(0.01)  # Allow hook to execute

    assert len(call_count) == 1
    assert call_count[0] == Stage.IN_PROGRESS


@pytest.mark.asyncio
async def test_on_transition_fired_on_move_to_review():
    """Test that on_transition is fired when task moves to review."""
    call_count = []

    async def my_hook(task):
        call_count.append(task.stage)

    hooks = {"on_transition": [my_hook]}
    board = AsyncKanbanBoard(persist_path=None, hooks=hooks)

    task = await board.create_task("Test", "Desc")
    await board.move_to_in_progress(task.id)
    call_count.clear()  # Clear previous hook calls

    await board.move_to_review(task.id)
    await asyncio.sleep(0.01)  # Allow hook to execute

    assert len(call_count) == 1
    assert call_count[0] == Stage.REVIEW


@pytest.mark.asyncio
async def test_on_done_fired_on_approve():
    """Test that on_done is fired when task is approved."""
    transition_count = []
    done_count = []

    async def transition_hook(task):
        transition_count.append(task.stage)

    async def done_hook(task):
        done_count.append(task.stage)

    hooks = {
        "on_transition": [transition_hook],
        "on_done": [done_hook],
    }
    board = AsyncKanbanBoard(persist_path=None, hooks=hooks)

    task = await board.create_task("Test", "Desc")
    await board.move_to_in_progress(task.id)
    await board.move_to_review(task.id)
    transition_count.clear()  # Clear previous calls

    await board.approve(task.id)
    await asyncio.sleep(0.01)  # Allow hooks to execute

    assert len(done_count) == 1
    assert done_count[0] == Stage.DONE
    assert len(transition_count) == 1  # on_transition also fired


@pytest.mark.asyncio
async def test_multiple_hooks_for_same_event():
    """Test that multiple hooks can be registered for the same event."""
    call_count = []

    async def hook1(task):
        call_count.append(1)

    async def hook2(task):
        call_count.append(2)

    hooks = {"on_transition": [hook1, hook2]}
    board = AsyncKanbanBoard(persist_path=None, hooks=hooks)

    await board.create_task("Test", "Desc")
    await asyncio.sleep(0.01)  # Allow hooks to execute

    assert len(call_count) == 2
    assert 1 in call_count
    assert 2 in call_count


@pytest.mark.asyncio
async def test_hook_fires_after_lock_release():
    """Test that hooks fire after the lock is released."""
    lock_acquired_count = []

    async def lock_checking_hook(task):
        # Try to acquire the lock - should succeed since hook runs after lock release
        async with board._lock:
            lock_acquired_count.append(1)

    hooks = {"on_transition": [lock_checking_hook]}
    board = AsyncKanbanBoard(persist_path=None, hooks=hooks)

    await board.create_task("Test", "Desc")
    await asyncio.sleep(0.01)  # Allow hook to execute

    assert len(lock_acquired_count) == 1


@pytest.mark.asyncio
async def test_task_state_at_hook_call_time():
    """Test that hook sees correct task state at call time."""
    captured_tasks = []

    async def capturing_hook(task):
        captured_tasks.append((task.id, task.stage))

    hooks = {"on_transition": [capturing_hook]}
    board = AsyncKanbanBoard(persist_path=None, hooks=hooks)

    task = await board.create_task("Test", "Desc")
    await asyncio.sleep(0.01)

    assert len(captured_tasks) == 1
    assert captured_tasks[0][0] == task.id
    assert captured_tasks[0][1] == Stage.BACKLOG

    captured_tasks.clear()
    await board.move_to_in_progress(task.id)
    await asyncio.sleep(0.01)

    assert len(captured_tasks) == 1
    assert captured_tasks[0][1] == Stage.IN_PROGRESS


@pytest.mark.asyncio
async def test_built_in_log_transition_hook():
    """Test the built-in log_transition hook."""
    hooks = {"on_transition": [log_transition]}
    board = AsyncKanbanBoard(persist_path=None, hooks=hooks)

    # Should not raise
    task = await board.create_task("Test", "Desc")
    await asyncio.sleep(0.01)

    await board.move_to_in_progress(task.id)
    await asyncio.sleep(0.01)
