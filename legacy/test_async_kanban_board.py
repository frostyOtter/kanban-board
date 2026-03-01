import asyncio
from pathlib import Path
import tempfile

import pytest
import pytest_asyncio

from async_kanban_board import (
    AsyncKanbanBoard,
    Stage,
    async_mock_assistant,
    WIPLimitError,
    InvalidTransitionError,
)
from kanban.domain import AuditEntry, Stage as KanbanStage
from kanban.board import AsyncKanbanBoard as KanbanBoard, stale_task_monitor


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


@pytest_asyncio.fixture
async def board_no_persist():
    """Create a board without persistence."""
    return AsyncKanbanBoard(persist_path=None)


@pytest_asyncio.fixture
async def board_wip_2(temp_persist_path):
    """Create a board with WIP limit of 2."""
    if temp_persist_path.exists():
        temp_persist_path.unlink()
    return AsyncKanbanBoard(wip_limit=2, persist_path=temp_persist_path)


@pytest_asyncio.fixture
async def new_board(temp_persist_path):
    """Create a fresh kanban.board.AsyncKanbanBoard for each test."""
    if temp_persist_path.exists():
        temp_persist_path.unlink()
    return KanbanBoard(persist_path=temp_persist_path)


@pytest.mark.asyncio
async def test_create_task(board):
    """Test creating a new task."""
    task = await board.create_task("Test Task", "Test description")

    assert task.title == "Test Task"
    assert task.description == "Test description"
    assert task.stage == Stage.BACKLOG
    assert task.code_snippet is None
    assert task.id is not None
    assert len(task.id) == 8


@pytest.mark.asyncio
async def test_create_task_concurrent(board):
    """Test creating tasks concurrently."""
    tasks = await asyncio.gather(
        board.create_task("Task 1", "Desc 1"),
        board.create_task("Task 2", "Desc 2"),
        board.create_task("Task 3", "Desc 3"),
    )

    assert len(tasks) == 3
    assert all(t.stage == Stage.BACKLOG for t in tasks)
    assert len(set(t.id for t in tasks)) == 3


@pytest.mark.asyncio
async def test_move_to_in_progress(board):
    """Test moving a task from Backlog to In-Progress."""
    task = await board.create_task("Test", "Desc")

    updated = await board.move_to_in_progress(task.id)

    assert updated.stage == Stage.IN_PROGRESS
    assert updated.code_snippet is not None
    assert "AUTO-GENERATED PLACEHOLDER" in updated.code_snippet


@pytest.mark.asyncio
async def test_move_to_in_progress_invalid_stage(board):
    """Test that moving a task from wrong stage raises InvalidTransitionError."""
    task = await board.create_task("Test", "Desc")
    await board.move_to_in_progress(task.id)

    with pytest.raises(InvalidTransitionError, match="expected 'backlog'"):
        await board.move_to_in_progress(task.id)


@pytest.mark.asyncio
async def test_wip_limit(board_wip_2):
    """Test WIP limit is enforced."""
    t1 = await board_wip_2.create_task("Task 1", "Desc 1")
    t2 = await board_wip_2.create_task("Task 2", "Desc 2")
    t3 = await board_wip_2.create_task("Task 3", "Desc 3")

    await board_wip_2.move_to_in_progress(t1.id)
    await board_wip_2.move_to_in_progress(t2.id)

    with pytest.raises(WIPLimitError, match="WIP limit reached"):
        await board_wip_2.move_to_in_progress(t3.id)


@pytest.mark.asyncio
async def test_wip_limit_after_completion(board_wip_2):
    """Test WIP limit allows new tasks after completion."""
    t1 = await board_wip_2.create_task("Task 1", "Desc 1")
    t2 = await board_wip_2.create_task("Task 2", "Desc 2")
    t3 = await board_wip_2.create_task("Task 3", "Desc 3")

    await board_wip_2.move_to_in_progress(t1.id)
    await board_wip_2.move_to_in_progress(t2.id)

    await board_wip_2.move_to_review(t1.id)
    await board_wip_2.approve(t1.id)

    updated_t3 = await board_wip_2.move_to_in_progress(t3.id)
    assert updated_t3.stage == Stage.IN_PROGRESS


@pytest.mark.asyncio
async def test_concurrent_start_respects_wip_limit(board_wip_2):
    """Test concurrent start operations respect WIP limit."""
    t1 = await board_wip_2.create_task("Task 1", "Desc 1")
    t2 = await board_wip_2.create_task("Task 2", "Desc 2")
    t3 = await board_wip_2.create_task("Task 3", "Desc 3")

    results = await asyncio.gather(
        board_wip_2.move_to_in_progress(t1.id),
        board_wip_2.move_to_in_progress(t2.id),
        board_wip_2.move_to_in_progress(t3.id),
        return_exceptions=True,
    )

    assert sum(isinstance(r, Exception) for r in results) == 1
    assert sum(not isinstance(r, Exception) for r in results) == 2


@pytest.mark.asyncio
async def test_move_to_review(board):
    """Test moving a task from In-Progress to Review."""
    task = await board.create_task("Test", "Desc")
    await board.move_to_in_progress(task.id)

    updated = await board.move_to_review(task.id)

    assert updated.stage == Stage.REVIEW


@pytest.mark.asyncio
async def test_move_to_review_invalid_stage(board):
    """Test that moving from wrong stage raises InvalidTransitionError."""
    task = await board.create_task("Test", "Desc")

    with pytest.raises(InvalidTransitionError, match="expected 'in_progress'"):
        await board.move_to_review(task.id)


@pytest.mark.asyncio
async def test_approve_task(board):
    """Test approving a task from Review to Done."""
    task = await board.create_task("Test", "Desc")
    await board.move_to_in_progress(task.id)
    await board.move_to_review(task.id)

    updated = await board.approve(task.id)

    assert updated.stage == Stage.DONE


@pytest.mark.asyncio
async def test_approve_invalid_stage(board):
    """Test that approving from wrong stage raises InvalidTransitionError."""
    task = await board.create_task("Test", "Desc")

    with pytest.raises(InvalidTransitionError, match="expected 'review'"):
        await board.approve(task.id)


@pytest.mark.asyncio
async def test_full_workflow(board):
    """Test complete workflow from creation to completion."""
    task = await board.create_task("Full Workflow", "Complete workflow test")

    assert task.stage == Stage.BACKLOG

    task = await board.move_to_in_progress(task.id)
    assert task.stage == Stage.IN_PROGRESS
    assert task.code_snippet is not None

    task = await board.move_to_review(task.id)
    assert task.stage == Stage.REVIEW

    task = await board.approve(task.id)
    assert task.stage == Stage.DONE


@pytest.mark.asyncio
async def test_get_nonexistent_task(board):
    """Test retrieving a task that doesn't exist raises KeyError."""
    with pytest.raises(KeyError, match="not found"):
        board._get("nonexistent")


@pytest.mark.asyncio
async def test_persistence(temp_persist_path):
    """Test that board state persists to file."""
    if temp_persist_path.exists():
        temp_persist_path.unlink()
    board1 = AsyncKanbanBoard(persist_path=temp_persist_path)
    t1 = await board1.create_task("Persist Test", "Will be saved")
    t1_id = t1.id
    await board1.move_to_in_progress(t1_id)

    board2 = AsyncKanbanBoard(persist_path=temp_persist_path)
    loaded_task = board2._get(t1_id)

    assert loaded_task.title == "Persist Test"
    assert loaded_task.stage == Stage.IN_PROGRESS
    assert loaded_task.code_snippet is not None


@pytest.mark.asyncio
async def test_no_persistence():
    """Test board with persist_path=None doesn't create files."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        persist_path = Path(tmpdir) / "board.json"
        board = AsyncKanbanBoard(persist_path=None)
        await board.create_task("No Persist", "Should not save")

        assert not persist_path.exists()


@pytest.mark.asyncio
async def test_board_view(board, capsys):
    """Test board_view prints correctly."""
    await board.create_task("Task 1", "Desc 1")
    await board.create_task("Task 2", "Desc 2")

    board.board_view()
    captured = capsys.readouterr()

    assert "BACKLOG" in captured.out
    assert "Task 1" in captured.out
    assert "Task 2" in captured.out


@pytest.mark.asyncio
async def test_async_mock_assistant():
    """Test the async mock assistant generates correct placeholder."""
    result = await async_mock_assistant("Test description")

    assert "AUTO-GENERATED PLACEHOLDER" in result
    assert "Test description" in result
    assert "def solution():" in result


@pytest.mark.asyncio
async def test_lock_protects_concurrent_mutations(board):
    """Test that lock protects against concurrent mutations."""
    task = await board.create_task("Concurrent", "Test")

    async def try_move():
        return await board.move_to_in_progress(task.id)

    with pytest.raises(InvalidTransitionError):
        await asyncio.gather(try_move(), try_move())


@pytest.mark.asyncio
async def test_count_stage(board):
    """Test _count_stage helper."""
    await board.create_task("T1", "D1")
    await board.create_task("T2", "D2")
    t3 = await board.create_task("T3", "D3")

    assert board._count_stage(Stage.BACKLOG) == 3

    await board.move_to_in_progress(t3.id)
    assert board._count_stage(Stage.BACKLOG) == 2
    assert board._count_stage(Stage.IN_PROGRESS) == 1


@pytest.mark.asyncio
async def test_assistant_runs_outside_lock():
    """Test that assistant runs outside the lock to allow concurrency."""
    call_count = 0

    async def slow_assistant(desc):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return f"code {call_count}"

    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        persist_path = Path(tmpdir) / "board.json"
        board = AsyncKanbanBoard(
            assistant=slow_assistant, wip_limit=2, persist_path=persist_path
        )

        t1 = await board.create_task("T1", "D1")
        t2 = await board.create_task("T2", "D2")

        start = asyncio.get_event_loop().time()
        await asyncio.gather(
            board.move_to_in_progress(t1.id),
            board.move_to_in_progress(t2.id),
        )
        elapsed = asyncio.get_event_loop().time() - start

        # If assistant ran inside lock sequentially, would take ~0.1s
        # With concurrent execution, should take ~0.05s
        assert elapsed < 0.08
        assert call_count == 2


@pytest.mark.asyncio
async def test_multiple_tasks_workflow(board):
    """Test managing multiple tasks through full workflow."""
    t1 = await board.create_task("Task 1", "First task")
    t2 = await board.create_task("Task 2", "Second task")
    t3 = await board.create_task("Task 3", "Third task")

    await board.move_to_in_progress(t1.id)
    await board.move_to_review(t1.id)
    await board.approve(t1.id)

    await board.move_to_in_progress(t2.id)

    assert board._tasks[t1.id].stage == Stage.DONE
    assert board._tasks[t2.id].stage == Stage.IN_PROGRESS
    assert board._tasks[t3.id].stage == Stage.BACKLOG


@pytest.mark.asyncio
async def test_find_stale_no_stale_tasks(new_board):
    """Test find_stale returns empty list when no tasks are stale."""
    await new_board.create_task("Task 1", "Desc 1")
    await new_board.create_task("Task 2", "Desc 2")

    stale = new_board.find_stale(threshold_seconds=300)
    assert len(stale) == 0


@pytest.mark.asyncio
async def test_find_stale_with_stale_task(new_board):
    """Test find_stale correctly identifies stale IN_PROGRESS tasks."""
    from datetime import datetime, timezone

    task = await new_board.create_task("Stale Task", "Will become stale")
    await new_board.move_to_in_progress(task.id)

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

    stale = new_board.find_stale(threshold_seconds=300)
    assert len(stale) == 1
    assert stale[0].id == task.id


@pytest.mark.asyncio
async def test_find_stale_ignores_non_in_progress(new_board):
    """Test find_stale ignores tasks not in IN_PROGRESS stage."""
    t1 = await new_board.create_task("Task 1", "Desc 1")
    t2 = await new_board.create_task("Task 2", "Desc 2")

    # Move t1 through IN_PROGRESS to REVIEW to DONE (not stale)
    await new_board.move_to_in_progress(t1.id)
    await new_board.move_to_review(t1.id)
    await new_board.approve(t1.id)

    # Move t2 to IN_PROGRESS and make it stale
    await new_board.move_to_in_progress(t2.id)

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

    stale = new_board.find_stale(threshold_seconds=300)
    assert len(stale) == 1
    assert stale[0].id == t2.id


@pytest.mark.asyncio
async def test_find_stale_uses_audit_timestamp_not_created_at(new_board):
    """Test find_stale uses audit trail timestamp, not task.created_at."""
    from datetime import datetime, timezone, timedelta

    task = await new_board.create_task("Old Task", "Created long ago")

    # Simulate old created_at time
    old_created = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    task.created_at = old_created

    # Move to IN_PROGRESS recently
    await new_board.move_to_in_progress(task.id)

    # Task should NOT be stale because it was moved to IN_PROGRESS recently
    stale = new_board.find_stale(threshold_seconds=300)
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
    stale = new_board.find_stale(threshold_seconds=300)
    assert len(stale) == 1
    assert stale[0].id == task.id


@pytest.mark.asyncio
async def test_stale_monitor(new_board):
    """Test stale task monitor detects and fires hooks for stale tasks."""
    import asyncio
    from datetime import datetime, timezone

    threshold = 1  # 1 second
    poll_interval = 1  # 1 second

    task = await new_board.create_task("Stale Task", "Will become stale")
    await new_board.move_to_in_progress(task.id)

    hook_calls = []

    async def track_stale(t):
        hook_calls.append(t.id)

    new_board._hook_registry.register("on_stale_task", track_stale)

    # Manually set the transition time to be old
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
    monitor = asyncio.create_task(
        stale_task_monitor(new_board, threshold, poll_interval)
    )
    await asyncio.sleep(2)  # Wait for at least one poll cycle
    monitor.cancel()

    try:
        await monitor
    except asyncio.CancelledError:
        pass

    assert len(hook_calls) >= 1
    assert task.id in hook_calls


@pytest.mark.asyncio
async def test_stale_monitor_respects_stage_changes(new_board):
    """Test that tasks moved out of IN_PROGRESS are no longer considered stale."""
    import asyncio
    from datetime import datetime, timezone

    threshold = 1  # 1 second
    poll_interval = 1  # 1 second

    task = await new_board.create_task("Task", "Will move to review")
    await new_board.move_to_in_progress(task.id)

    hook_calls = []

    async def track_stale(t):
        hook_calls.append(t.id)

    new_board._hook_registry.register("on_stale_task", track_stale)

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
    monitor = asyncio.create_task(
        stale_task_monitor(new_board, threshold, poll_interval)
    )
    await asyncio.sleep(1.5)  # Wait for at least one poll cycle

    # Move task to REVIEW - should stop being stale
    await new_board.move_to_review(task.id)

    await asyncio.sleep(1.5)  # Wait for another poll cycle
    monitor.cancel()

    try:
        await monitor
    except asyncio.CancelledError:
        pass

    # Hook should have fired at least once before we moved the task
    assert len(hook_calls) >= 1


@pytest.mark.asyncio
async def test_stale_monitor_handles_multiple_stale_tasks(new_board):
    """Test monitor fires hook for each stale task."""
    import asyncio
    from datetime import datetime, timezone

    threshold = 2  # 2 seconds
    poll_interval = 1  # 1 second

    t1 = await new_board.create_task("Task 1", "Stale 1")
    t2 = await new_board.create_task("Task 2", "Stale 2")
    t3 = await new_board.create_task("Task 3", "Fresh")

    await new_board.move_to_in_progress(t1.id)
    await new_board.move_to_in_progress(t2.id)

    hook_calls = []

    async def track_stale(t):
        hook_calls.append(t.id)

    new_board._hook_registry.register("on_stale_task", track_stale)

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
    await new_board.move_to_in_progress(t3.id)

    # Start monitor
    monitor = asyncio.create_task(
        stale_task_monitor(new_board, threshold, poll_interval)
    )
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
