import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from kanban_board import KanbanBoard, Stage, mock_assistant


@pytest.fixture
def temp_persist_path():
    """Create a temporary file path for board persistence."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
        path = Path(f.name)
    yield path
    if path.exists():
        path.unlink()


@pytest.fixture
def board(temp_persist_path):
    """Create a fresh board for each test."""
    # Delete empty file first
    if temp_persist_path.exists():
        temp_persist_path.unlink()
    return KanbanBoard(assistant=mock_assistant, persist_path=temp_persist_path)


@pytest.fixture
def board_no_persist():
    """Create a board without persistence."""
    return KanbanBoard(persist_path=None)


@pytest.fixture
def custom_assistant():
    """Create a mock assistant for testing."""
    return MagicMock(return_value="custom code snippet")


def test_create_task(board):
    """Test creating a new task."""
    task = board.create_task("Test Task", "Test description")

    assert task.title == "Test Task"
    assert task.description == "Test description"
    assert task.stage == Stage.BACKLOG
    assert task.code_snippet is None
    assert task.id is not None
    assert len(task.id) == 8


def test_create_task_with_custom_assistant(custom_assistant, temp_persist_path):
    """Test creating a board with a custom assistant."""
    board = KanbanBoard(persist_path=None, assistant=custom_assistant)
    task = board.create_task("Test", "Desc")

    board.move_to_in_progress(task.id)

    assert custom_assistant.called
    assert task.code_snippet == "custom code snippet"


def test_move_to_in_progress(board):
    """Test moving a task from Backlog to In-Progress."""
    task = board.create_task("Test", "Desc")

    updated = board.move_to_in_progress(task.id)

    assert updated.stage == Stage.IN_PROGRESS
    assert updated.code_snippet is not None
    assert "AUTO-GENERATED PLACEHOLDER" in updated.code_snippet


def test_move_to_in_progress_invalid_stage(board):
    """Test that moving a task from wrong stage raises ValueError."""
    task = board.create_task("Test", "Desc")
    board.move_to_in_progress(task.id)

    with pytest.raises(ValueError, match="expected 'backlog'"):
        board.move_to_in_progress(task.id)


def test_move_to_review(board):
    """Test moving a task from In-Progress to Review."""
    task = board.create_task("Test", "Desc")
    board.move_to_in_progress(task.id)

    updated = board.move_to_review(task.id)

    assert updated.stage == Stage.REVIEW


def test_move_to_review_invalid_stage(board):
    """Test that moving from wrong stage raises ValueError."""
    task = board.create_task("Test", "Desc")

    with pytest.raises(ValueError, match="expected 'in_progress'"):
        board.move_to_review(task.id)


def test_approve_task(board):
    """Test approving a task from Review to Done."""
    task = board.create_task("Test", "Desc")
    board.move_to_in_progress(task.id)
    board.move_to_review(task.id)

    updated = board.approve(task.id)

    assert updated.stage == Stage.DONE


def test_approve_invalid_stage(board):
    """Test that approving from wrong stage raises ValueError."""
    task = board.create_task("Test", "Desc")

    with pytest.raises(ValueError, match="expected 'review'"):
        board.approve(task.id)


def test_full_workflow(board):
    """Test complete workflow from creation to completion."""
    task = board.create_task("Full Workflow", "Complete workflow test")

    assert task.stage == Stage.BACKLOG

    task = board.move_to_in_progress(task.id)
    assert task.stage == Stage.IN_PROGRESS
    assert task.code_snippet is not None

    task = board.move_to_review(task.id)
    assert task.stage == Stage.REVIEW

    task = board.approve(task.id)
    assert task.stage == Stage.DONE


def test_get_nonexistent_task(board):
    """Test retrieving a task that doesn't exist raises KeyError."""
    with pytest.raises(KeyError, match="not found"):
        board._get("nonexistent")


def test_multiple_tasks(board):
    """Test managing multiple tasks."""
    t1 = board.create_task("Task 1", "First task")
    t2 = board.create_task("Task 2", "Second task")
    t3 = board.create_task("Task 3", "Third task")

    board.move_to_in_progress(t1.id)
    board.move_to_review(t1.id)
    board.approve(t1.id)

    board.move_to_in_progress(t2.id)

    assert board._tasks[t1.id].stage == Stage.DONE
    assert board._tasks[t2.id].stage == Stage.IN_PROGRESS
    assert board._tasks[t3.id].stage == Stage.BACKLOG


def test_persistence(temp_persist_path):
    """Test that board state persists to file."""
    # Delete the empty file first so board1 starts fresh
    if temp_persist_path.exists():
        temp_persist_path.unlink()
    board1 = KanbanBoard(persist_path=temp_persist_path, assistant=mock_assistant)
    t1 = board1.create_task("Persist Test", "Will be saved")
    t1_id = t1.id
    board1.move_to_in_progress(t1_id)

    board2 = KanbanBoard(persist_path=temp_persist_path, assistant=mock_assistant)
    loaded_task = board2._get(t1_id)

    assert loaded_task.title == "Persist Test"
    assert loaded_task.stage == Stage.IN_PROGRESS
    assert loaded_task.code_snippet is not None


def test_no_persistence():
    """Test board with persist_path=None doesn't create files."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        persist_path = Path(tmpdir) / "board.json"
        board = KanbanBoard(persist_path=None)
        board.create_task("No Persist", "Should not save")

        assert not persist_path.exists()


def test_board_view(board, capsys):
    """Test board_view prints correctly."""
    board.create_task("Task 1", "Desc 1")
    board.create_task("Task 2", "Desc 2")

    board.board_view()
    captured = capsys.readouterr()

    assert "BACKLOG" in captured.out
    assert "Task 1" in captured.out
    assert "Task 2" in captured.out


def test_task_string_representation(board):
    """Test Task __str__ method."""
    task = board.create_task("Test Task", "Test description")

    str_repr = str(task)

    assert task.id in str_repr
    assert "Test Task" in str_repr
    assert "backlog" in str_repr


def test_task_string_representation_with_snippet(board):
    """Test Task __str__ with code snippet."""
    task = board.create_task("Test", "Desc")
    board.move_to_in_progress(task.id)

    str_repr = str(task)

    assert "snippet:" in str_repr


def test_mock_assistant():
    """Test the mock assistant generates correct placeholder."""
    result = mock_assistant("Test description for coding")

    assert "AUTO-GENERATED PLACEHOLDER" in result
    assert "Test description for coding" in result
    assert "def solution():" in result


def test_create_task_saves_persistence(temp_persist_path):
    """Test that creating a task triggers save."""
    # Delete empty file first
    if temp_persist_path.exists():
        temp_persist_path.unlink()
    board = KanbanBoard(persist_path=temp_persist_path, assistant=mock_assistant)
    board.create_task("Save Test", "Test save on create")

    assert temp_persist_path.exists()


def test_move_task_saves_persistence(temp_persist_path):
    """Test that moving a task triggers save."""
    # Delete empty file first
    if temp_persist_path.exists():
        temp_persist_path.unlink()
    board = KanbanBoard(persist_path=temp_persist_path, assistant=mock_assistant)
    task = board.create_task("Move Test", "Test save on move")
    initial_mtime = temp_persist_path.stat().st_mtime

    import time

    time.sleep(0.01)
    board.move_to_in_progress(task.id)

    assert temp_persist_path.stat().st_mtime > initial_mtime
