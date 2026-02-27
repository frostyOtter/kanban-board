"""
FastAPI REST API — thin HTTP wrapper over AsyncKanbanBoard.

Responsibilities (only):
  - Parse and validate HTTP input (via Pydantic request schemas)
  - Delegate to the board
  - Translate board exceptions → HTTP status codes
  - Serialise Task → response schema

Board logic (WIP limit, dependencies, transitions) lives entirely in
board.py — nothing is duplicated here.

Endpoints:
  POST   /tasks                       Create a task
  GET    /tasks                       List all tasks (optional ?stage= filter)
  GET    /tasks/{id}                  Get a single task
  POST   /tasks/{id}/start            Backlog → In-Progress
  POST   /tasks/{id}/review           In-Progress → Review
  POST   /tasks/{id}/approve          Review → Done
  GET    /board                       Board snapshot (all stages)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .board import AsyncKanbanBoard
from .domain import (
    AuditEntry,
    BoardError,
    InvalidTransitionError,
    Stage,
    Task,
    TaskNotFoundError,
    UnresolvedDependencyError,
    WIPLimitError,
)


# ---------------------------------------------------------------------------
# Shared board instance (created once at startup)
# ---------------------------------------------------------------------------

_board: AsyncKanbanBoard | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _board
    _board = AsyncKanbanBoard()
    yield


def get_board() -> AsyncKanbanBoard:
    assert _board is not None, "Board not initialised"
    return _board


BoardDep = Annotated[AsyncKanbanBoard, Depends(get_board)]


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class CreateTaskRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    description: str = Field(..., min_length=1)
    depends_on: list[str] = Field(default_factory=list)


class AuditEntryResponse(BaseModel):
    from_stage: Stage | None
    to_stage: Stage
    timestamp: str
    note: str | None

    @classmethod
    def from_entry(cls, entry: AuditEntry) -> "AuditEntryResponse":
        return cls(
            from_stage=entry.from_stage,
            to_stage=entry.to_stage,
            timestamp=entry.timestamp,
            note=entry.note,
        )


class TaskResponse(BaseModel):
    id: str
    title: str
    description: str
    stage: Stage
    created_at: str
    code_snippet: str | None
    depends_on: list[str]
    history: list[AuditEntryResponse]
    review_notes: str | None

    @classmethod
    def from_task(cls, task: Task) -> "TaskResponse":
        return cls(
            id=task.id,
            title=task.title,
            description=task.description,
            stage=task.stage,
            created_at=task.created_at,
            code_snippet=task.code_snippet,
            depends_on=task.depends_on,
            history=[AuditEntryResponse.from_entry(e) for e in task.history],
            review_notes=task.review_notes,
        )


class BoardSnapshot(BaseModel):
    backlog: list[TaskResponse]
    in_progress: list[TaskResponse]
    review: list[TaskResponse]
    done: list[TaskResponse]


# ---------------------------------------------------------------------------
# Exception → HTTP translation
# ---------------------------------------------------------------------------


def _http(exc: BoardError) -> HTTPException:
    """Map domain exceptions to appropriate HTTP status codes."""
    if isinstance(exc, TaskNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, WIPLimitError):
        return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, UnresolvedDependencyError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, InvalidTransitionError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Kanban Board API",
    version="2.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(body: CreateTaskRequest, board: BoardDep) -> TaskResponse:
    try:
        task = await board.create_task(
            title=body.title,
            description=body.description,
            depends_on=body.depends_on,
        )
    except BoardError as exc:
        raise _http(exc)
    return TaskResponse.from_task(task)


@app.get("/tasks", response_model=list[TaskResponse])
def list_tasks(
    board: BoardDep,
    stage: Stage | None = Query(default=None, description="Filter by stage"),
) -> list[TaskResponse]:
    tasks = board.tasks_by_stage(stage) if stage else board.all_tasks()
    return [TaskResponse.from_task(t) for t in tasks]


@app.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, board: BoardDep) -> TaskResponse:
    try:
        return TaskResponse.from_task(board.get_task(task_id))
    except TaskNotFoundError as exc:
        raise _http(exc)


@app.post("/tasks/{task_id}/start", response_model=TaskResponse)
async def start_task(task_id: str, board: BoardDep) -> TaskResponse:
    try:
        task = await board.move_to_in_progress(task_id)
    except BoardError as exc:
        raise _http(exc)
    return TaskResponse.from_task(task)


@app.post("/tasks/{task_id}/review", response_model=TaskResponse)
async def review_task(task_id: str, board: BoardDep) -> TaskResponse:
    try:
        task = await board.move_to_review(task_id)
    except BoardError as exc:
        raise _http(exc)
    return TaskResponse.from_task(task)


@app.post("/tasks/{task_id}/approve", response_model=TaskResponse)
async def approve_task(task_id: str, board: BoardDep) -> TaskResponse:
    try:
        task = await board.approve(task_id)
    except BoardError as exc:
        raise _http(exc)
    return TaskResponse.from_task(task)


@app.get("/board", response_model=BoardSnapshot)
def board_view(board: BoardDep) -> BoardSnapshot:
    return BoardSnapshot(
        backlog=[
            TaskResponse.from_task(t) for t in board.tasks_by_stage(Stage.BACKLOG)
        ],
        in_progress=[
            TaskResponse.from_task(t) for t in board.tasks_by_stage(Stage.IN_PROGRESS)
        ],
        review=[TaskResponse.from_task(t) for t in board.tasks_by_stage(Stage.REVIEW)],
        done=[TaskResponse.from_task(t) for t in board.tasks_by_stage(Stage.DONE)],
    )
