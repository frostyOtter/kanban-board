from pathlib import Path
import tempfile

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from kanban.api import app, CreateTaskRequest, TaskResponse, BoardSnapshot
from kanban.board import AsyncKanbanBoard
from kanban.domain import Stage, TaskNotFoundError, WIPLimitError
from kanban.assistants import async_mock_reviewer


@pytest.fixture
def temp_persist_path():
    """Create a temporary file path for board persistence."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
        path = Path(f.name)
    yield path
    if path.exists():
        path.unlink()


@pytest.fixture
def client(temp_persist_path):
    """Create a test client with fresh board state."""
    from kanban.api import _board

    _board = None

    # Delete empty file first
    if temp_persist_path.exists():
        temp_persist_path.unlink()

    from kanban.api import get_board

    app.dependency_overrides[get_board] = lambda: AsyncKanbanBoard(
        persist_path=temp_persist_path
    )

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def client_wip_1(temp_persist_path):
    """Create a test client with WIP limit of 1."""
    from kanban.api import _board

    _board = None

    # Delete empty file first
    if temp_persist_path.exists():
        temp_persist_path.unlink()

    from kanban.api import get_board

    app.dependency_overrides[get_board] = lambda: AsyncKanbanBoard(
        wip_limit=1, persist_path=temp_persist_path
    )

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_create_task(client):
    """Test POST /tasks endpoint."""
    response = client.post(
        "/tasks", json={"title": "Test Task", "description": "Test description"}
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Test Task"
    assert data["description"] == "Test description"
    assert data["stage"] == "backlog"
    assert data["code_snippet"] is None
    assert "id" in data
    assert "created_at" in data


def test_create_task_with_dependencies(client):
    """Test POST /tasks with depends_on field."""
    # Create a dependency task first
    dep_response = client.post(
        "/tasks", json={"title": "Dependency", "description": "Must complete first"}
    )
    dep_id = dep_response.json()["id"]

    response = client.post(
        "/tasks",
        json={
            "title": "Dependent Task",
            "description": "Depends on first task",
            "depends_on": [dep_id],
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["depends_on"] == [dep_id]


def test_create_task_invalid_dependency():
    """Test POST /tasks with non-existent dependency returns 404."""
    # Create a fresh board that definitely doesn't have the dependency
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
        temp_path = Path(f.name)

    # Delete the empty file so board starts fresh
    temp_path.unlink()

    from kanban.api import get_board

    app.dependency_overrides[get_board] = lambda: AsyncKanbanBoard(
        persist_path=temp_path
    )

    with TestClient(app) as test_client:
        response = test_client.post(
            "/tasks",
            json={
                "title": "Task",
                "description": "Has invalid dependency",
                "depends_on": ["nonexistent123"],
            },
        )

    app.dependency_overrides.clear()

    # TaskNotFoundError returns 404
    assert response.status_code == 404


def test_create_task_validation(client):
    """Test POST /tasks validates input."""
    response = client.post("/tasks", json={"title": "", "description": "Test"})
    assert response.status_code == 422

    response = client.post("/tasks", json={"title": "T" * 121, "description": "Test"})
    assert response.status_code == 422


def test_list_tasks(client):
    """Test GET /tasks endpoint."""
    client.post("/tasks", json={"title": "Task 1", "description": "Desc 1"})
    client.post("/tasks", json={"title": "Task 2", "description": "Desc 2"})

    response = client.get("/tasks")

    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) == 2
    assert all("id" in t for t in tasks)
    assert all("title" in t for t in tasks)


def test_list_tasks_filter_by_stage(client):
    """Test GET /tasks with stage filter."""
    client.post("/tasks", json={"title": "T1", "description": "D1"})
    t2 = client.post("/tasks", json={"title": "T2", "description": "D2"})
    client.post(f"/tasks/{t2.json()['id']}/start")

    response = client.get("/tasks?stage=backlog")
    assert response.status_code == 200
    assert len(response.json()) == 1

    response = client.get("/tasks?stage=in_progress")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_list_tasks_invalid_stage(client):
    """Test GET /tasks with invalid stage."""
    response = client.get("/tasks?stage=invalid")
    assert response.status_code == 422


def test_get_task(client):
    """Test GET /tasks/{id} endpoint."""
    create_resp = client.post(
        "/tasks", json={"title": "Single Task", "description": "Get me"}
    )
    task_id = create_resp.json()["id"]

    response = client.get(f"/tasks/{task_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == task_id
    assert data["title"] == "Single Task"


def test_get_task_not_found(client):
    """Test GET /tasks/{id} with non-existent task."""
    response = client.get("/tasks/nonexistent")
    assert response.status_code == 404


def test_start_task(client):
    """Test POST /tasks/{id}/start endpoint."""
    task = client.post("/tasks", json={"title": "Start Me", "description": "Go"})
    task_id = task.json()["id"]

    response = client.post(f"/tasks/{task_id}/start")

    assert response.status_code == 200
    data = response.json()
    assert data["stage"] == "in_progress"
    assert data["code_snippet"] is not None


def test_start_task_invalid_stage(client):
    """Test starting a task not in backlog."""
    task = client.post("/tasks", json={"title": "Task", "description": "Desc"})
    task_id = task.json()["id"]
    client.post(f"/tasks/{task_id}/start")

    response = client.post(f"/tasks/{task_id}/start")
    assert response.status_code == 422


def test_start_task_not_found(client):
    """Test starting a non-existent task."""
    response = client.post("/tasks/nonexistent/start")
    assert response.status_code == 404


def test_start_task_wip_limit(client_wip_1):
    """Test starting task respects WIP limit."""
    t1 = client_wip_1.post("/tasks", json={"title": "T1", "description": "D1"})
    t2 = client_wip_1.post("/tasks", json={"title": "T2", "description": "D2"})

    client_wip_1.post(f"/tasks/{t1.json()['id']}/start")

    response = client_wip_1.post(f"/tasks/{t2.json()['id']}/start")
    assert response.status_code == 429


def test_review_task(client):
    """Test POST /tasks/{id}/review endpoint."""
    task = client.post("/tasks", json={"title": "Review Me", "description": "Check"})
    task_id = task.json()["id"]
    client.post(f"/tasks/{task_id}/start")

    response = client.post(f"/tasks/{task_id}/review")

    assert response.status_code == 200
    assert response.json()["stage"] == "review"


def test_review_task_invalid_stage(client):
    """Test reviewing a task not in in_progress."""
    task = client.post("/tasks", json={"title": "Task", "description": "Desc"})
    task_id = task.json()["id"]

    response = client.post(f"/tasks/{task_id}/review")
    assert response.status_code == 422


def test_review_task_not_found(client):
    """Test reviewing a non-existent task."""
    response = client.post("/tasks/nonexistent/review")
    assert response.status_code == 404


def test_approve_task(client):
    """Test POST /tasks/{id}/approve endpoint."""
    task = client.post("/tasks", json={"title": "Approve Me", "description": "Done"})
    task_id = task.json()["id"]
    client.post(f"/tasks/{task_id}/start")
    client.post(f"/tasks/{task_id}/review")

    response = client.post(f"/tasks/{task_id}/approve")

    assert response.status_code == 200
    assert response.json()["stage"] == "done"


def test_approve_task_invalid_stage(client):
    """Test approving a task not in review."""
    task = client.post("/tasks", json={"title": "Task", "description": "Desc"})
    task_id = task.json()["id"]

    response = client.post(f"/tasks/{task_id}/approve")
    assert response.status_code == 422


def test_approve_task_not_found(client):
    """Test approving a non-existent task."""
    response = client.post("/tasks/nonexistent/approve")
    assert response.status_code == 404


def test_board_view(client):
    """Test GET /board endpoint."""
    client.post("/tasks", json={"title": "Backlog Task", "description": "In backlog"})

    t2 = client.post(
        "/tasks", json={"title": "Active Task", "description": "In progress"}
    )
    t2_id = t2.json()["id"]
    client.post(f"/tasks/{t2_id}/start")

    response = client.get("/board")

    assert response.status_code == 200
    data = response.json()
    assert "backlog" in data
    assert "in_progress" in data
    assert "review" in data
    assert "done" in data
    assert len(data["backlog"]) == 1
    assert len(data["in_progress"]) == 1


def test_full_workflow_via_api(client):
    """Test complete workflow through API endpoints."""
    # Create
    task = client.post("/tasks", json={"title": "Workflow", "description": "Full test"})
    task_id = task.json()["id"]
    assert task.json()["stage"] == "backlog"

    # Start
    response = client.post(f"/tasks/{task_id}/start")
    assert response.json()["stage"] == "in_progress"
    assert response.json()["code_snippet"] is not None

    # Review
    response = client.post(f"/tasks/{task_id}/review")
    assert response.json()["stage"] == "review"

    # Approve
    response = client.post(f"/tasks/{task_id}/approve")
    assert response.json()["stage"] == "done"


def test_task_request_schema():
    """Test CreateTaskRequest schema validation."""
    # Valid request
    req = CreateTaskRequest(
        title="Test", description="Description", depends_on=["dep1", "dep2"]
    )
    assert req.title == "Test"
    assert req.depends_on == ["dep1", "dep2"]

    # Default depends_on
    req = CreateTaskRequest(title="Test", description="Desc")
    assert req.depends_on == []

    # Invalid - empty title
    with pytest.raises(ValidationError):
        CreateTaskRequest(title="", description="Desc")

    # Invalid - title too long
    with pytest.raises(ValidationError):
        CreateTaskRequest(title="T" * 121, description="Desc")


def test_task_response_schema():
    """Test TaskResponse schema."""
    response = TaskResponse(
        id="123",
        title="Task",
        description="Desc",
        stage=Stage.DONE,
        created_at="2024-01-01T00:00:00+00:00",
        code_snippet="code",
        depends_on=[],
        history=[],
        review_notes=None,
    )
    assert response.id == "123"
    assert response.stage == Stage.DONE


def test_task_response_from_task():
    """Test TaskResponse.from_task class method."""
    from kanban.domain import Task

    task = Task(
        title="Test",
        description="Desc",
        id="abc123",
        stage=Stage.IN_PROGRESS,
        created_at="2024-01-01T00:00:00+00:00",
        code_snippet="snippet",
        depends_on=["dep1"],
    )

    response = TaskResponse.from_task(task)
    assert response.id == "abc123"
    assert response.title == "Test"
    assert response.depends_on == ["dep1"]


def test_board_snapshot_schema():
    """Test BoardSnapshot schema."""
    snapshot = BoardSnapshot(backlog=[], in_progress=[], review=[], done=[])
    assert snapshot.backlog == []
    assert snapshot.in_progress == []


def test_exception_to_http_translation():
    """Test that domain exceptions map to correct HTTP status codes."""
    from kanban.api import _http
    from kanban.domain import UnresolvedDependencyError, InvalidTransitionError

    # TaskNotFoundError -> 404
    exc = TaskNotFoundError("task123")
    http_exc = _http(exc)
    assert http_exc.status_code == 404

    # WIPLimitError -> 429
    exc = WIPLimitError(current=3, limit=3)
    http_exc = _http(exc)
    assert http_exc.status_code == 429

    # UnresolvedDependencyError -> 409
    exc = UnresolvedDependencyError(task_id="t1", blocking=["dep1"])
    http_exc = _http(exc)
    assert http_exc.status_code == 409

    # InvalidTransitionError -> 422
    exc = InvalidTransitionError(
        task_id="t1", current=Stage.DONE, expected=Stage.BACKLOG
    )
    http_exc = _http(exc)
    assert http_exc.status_code == 422


def test_create_multiple_tasks(client):
    """Test creating and managing multiple tasks."""
    ids = []
    for i in range(5):
        resp = client.post(
            "/tasks", json={"title": f"Task {i}", "description": f"Description {i}"}
        )
        ids.append(resp.json()["id"])

    response = client.get("/tasks")
    assert len(response.json()) == 5

    # Move some through stages
    client.post(f"/tasks/{ids[0]}/start")
    client.post(f"/tasks/{ids[0]}/review")
    client.post(f"/tasks/{ids[0]}/approve")

    client.post(f"/tasks/{ids[1]}/start")

    board = client.get("/board").json()
    assert len(board["done"]) == 1
    assert len(board["in_progress"]) == 1
    assert len(board["backlog"]) == 3


def test_task_with_blocked_dependencies(client):
    """Test that tasks with unresolved dependencies can't start."""
    # Create task with dependency
    t1 = client.post("/tasks", json={"title": "Dep", "description": "Must finish"})
    dep_id = t1.json()["id"]

    t2 = client.post(
        "/tasks",
        json={"title": "Dependent", "description": "Blocked", "depends_on": [dep_id]},
    )
    dependent_id = t2.json()["id"]

    # Try to start dependent task before dependency is done
    response = client.post(f"/tasks/{dependent_id}/start")
    assert response.status_code == 409

    # Complete the dependency
    client.post(f"/tasks/{dep_id}/start")
    client.post(f"/tasks/{dep_id}/review")
    client.post(f"/tasks/{dep_id}/approve")

    # Now dependent task can start
    response = client.post(f"/tasks/{dependent_id}/start")
    assert response.status_code == 200


def test_reviewer_sets_review_notes():
    """Test that reviewer populates review_notes after move_to_review."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
        temp_path = Path(f.name)

    # Delete empty file
    temp_path.unlink()

    from kanban.api import get_board

    app.dependency_overrides[get_board] = lambda: AsyncKanbanBoard(
        persist_path=temp_path, reviewer=async_mock_reviewer
    )

    with TestClient(app) as test_client:
        task = test_client.post(
            "/tasks", json={"title": "Review Test", "description": "Test with TODO"}
        )
        task_id = task.json()["id"]

        test_client.post(f"/tasks/{task_id}/start")

        response = test_client.post(f"/tasks/{task_id}/review")
        assert response.status_code == 200
        assert response.json()["review_notes"] is not None
        assert (
            "Review Checklist" in response.json()["review_notes"]
            or "✓ Code reviewed" in response.json()["review_notes"]
        )

        # Check GET /tasks/{id} returns review_notes
        get_response = test_client.get(f"/tasks/{task_id}")
        assert get_response.status_code == 200
        assert get_response.json()["review_notes"] is not None

    app.dependency_overrides.clear()


def test_reviewer_concurrent_with_board_operations():
    """Test that reviewer runs concurrently with other board operations."""
    import asyncio
    import time

    async def slow_reviewer(description, snippet):
        await asyncio.sleep(0.1)
        return f"Review for {description[:20]}"

    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
        temp_path = Path(f.name)

    temp_path.unlink()

    from kanban.api import get_board

    app.dependency_overrides[get_board] = lambda: AsyncKanbanBoard(
        persist_path=temp_path, reviewer=slow_reviewer
    )

    with TestClient(app) as test_client:
        t1 = test_client.post(
            "/tasks", json={"title": "T1", "description": "First task"}
        )
        t2 = test_client.post(
            "/tasks", json={"title": "T2", "description": "Second task"}
        )

        t1_id = t1.json()["id"]
        t2_id = t2.json()["id"]

        test_client.post(f"/tasks/{t1_id}/start")
        test_client.post(f"/tasks/{t2_id}/start")

        # Move t1 to review - reviewer will run concurrently
        start = time.time()
        test_client.post(f"/tasks/{t1_id}/review")

        # While reviewer runs, board should remain usable
        get_response = test_client.get(f"/tasks/{t2_id}")
        assert get_response.status_code == 200

        elapsed = time.time() - start
        assert elapsed < 0.2  # Should complete quickly even with slow reviewer

    app.dependency_overrides.clear()


def test_no_reviewer_no_review_notes():
    """Test that review_notes remains None when no reviewer is configured."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
        temp_path = Path(f.name)

    temp_path.unlink()

    from kanban.api import get_board

    app.dependency_overrides[get_board] = lambda: AsyncKanbanBoard(
        persist_path=temp_path
    )

    with TestClient(app) as test_client:
        task = test_client.post(
            "/tasks", json={"title": "No Reviewer", "description": "Test"}
        )
        task_id = task.json()["id"]

        test_client.post(f"/tasks/{task_id}/start")
        test_client.post(f"/tasks/{task_id}/review")

        response = test_client.get(f"/tasks/{task_id}")
        assert response.status_code == 200
        assert response.json()["review_notes"] is None

    app.dependency_overrides.clear()


def test_reviewer_persists_to_disk():
    """Test that review_notes are persisted to disk."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
        temp_path = Path(f.name)

    temp_path.unlink()

    from kanban.api import get_board

    app.dependency_overrides[get_board] = lambda: AsyncKanbanBoard(
        persist_path=temp_path, reviewer=async_mock_reviewer
    )

    with TestClient(app) as test_client:
        task = test_client.post(
            "/tasks",
            json={"title": "Persist Review", "description": "Test persistence"},
        )
        task_id = task.json()["id"]

        test_client.post(f"/tasks/{task_id}/start")
        test_client.post(f"/tasks/{task_id}/review")

        review_notes = test_client.get(f"/tasks/{task_id}").json()["review_notes"]
        assert review_notes is not None

    app.dependency_overrides.clear()

    # Create new board with same persist path
    app.dependency_overrides[get_board] = lambda: AsyncKanbanBoard(
        persist_path=temp_path
    )

    with TestClient(app) as test_client:
        response = test_client.get(f"/tasks/{task_id}")
        assert response.status_code == 200
        assert response.json()["review_notes"] == review_notes

    app.dependency_overrides.clear()
