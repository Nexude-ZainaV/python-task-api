"""FastAPI application: routes, dependency wiring and the app factory.

Run locally:  fastapi dev src/task_api/main.py
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status

from task_api.models import Priority, Status, Task, TaskCreate, TaskPage, TaskStats, TaskUpdate
from task_api.repository import SORT_COLUMNS, TaskRepository, connect, init_schema

DEFAULT_DB_PATH = "tasks.db"
MAX_PAGE_SIZE = 100

SortKey = Literal["created_at", "due_date", "priority", "title"]
assert set(SortKey.__args__) == set(SORT_COLUMNS), "SortKey must list every repository sort column"


def database_path() -> str:
    return os.environ.get("TASK_API_DB", DEFAULT_DB_PATH)


def get_repository() -> Iterator[TaskRepository]:
    """One connection per request, always closed, even when the handler raises."""
    connection = connect(database_path())
    try:
        yield TaskRepository(connection)
    finally:
        connection.close()


def today() -> date:
    return datetime.now(UTC).date()


Repo = Annotated[TaskRepository, Depends(get_repository)]
Today = Annotated[date, Depends(today)]


@asynccontextmanager
async def lifespan(_: FastAPI):
    connection = connect(database_path())
    try:
        init_schema(connection)
    finally:
        connection.close()
    yield


app = FastAPI(
    title="Task API",
    version="1.0.0",
    summary="A small task tracker: CRUD, filtering, search, sorting and stats.",
    lifespan=lifespan,
)


def _not_found(task_id: int) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"task {task_id} not found")


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tasks", status_code=status.HTTP_201_CREATED, tags=["tasks"])
def create_task(body: TaskCreate, repo: Repo, response: Response) -> Task:
    task = repo.create(body)
    response.headers["Location"] = f"/tasks/{task.id}"
    return task


@app.get("/tasks", tags=["tasks"])
def list_tasks(
    repo: Repo,
    status_filter: Annotated[Status | None, Query(alias="status")] = None,
    priority: Priority | None = None,
    q: Annotated[str | None, Query(max_length=100, description="Search title and description")] = None,
    sort: SortKey = "created_at",
    desc: bool = False,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TaskPage:
    items, total = repo.list(
        status=status_filter,
        priority=priority,
        search=q,
        sort=sort,
        descending=desc,
        limit=limit,
        offset=offset,
    )
    return TaskPage(items=items, total=total, limit=limit, offset=offset)


# Declared before /tasks/{task_id} so "stats" is not parsed as an id.
@app.get("/tasks/stats", tags=["tasks"])
def task_stats(repo: Repo, on: Today) -> TaskStats:
    return TaskStats(**repo.stats(on))


@app.get("/tasks/{task_id}", tags=["tasks"])
def get_task(task_id: int, repo: Repo) -> Task:
    task = repo.get(task_id)
    if task is None:
        raise _not_found(task_id)
    return task


@app.patch("/tasks/{task_id}", tags=["tasks"])
def update_task(task_id: int, body: TaskUpdate, repo: Repo) -> Task:
    task = repo.update(task_id, body)
    if task is None:
        raise _not_found(task_id)
    return task


@app.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["tasks"])
def delete_task(task_id: int, repo: Repo) -> None:
    if not repo.delete(task_id):
        raise _not_found(task_id)
