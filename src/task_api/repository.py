"""Data access for tasks on top of the standard-library sqlite3 module.

Every query is parameterised (``?`` placeholders), so user input never becomes SQL.
Sort columns cannot be parameterised, so they come from a fixed allow-list instead.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from typing import Any

from task_api.models import Priority, Status, Task, TaskCreate, TaskUpdate

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL CHECK (status IN ('todo', 'in_progress', 'done')),
    priority    TEXT    NOT NULL CHECK (priority IN ('low', 'medium', 'high')),
    due_date    TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tasks_status_due ON tasks (status, due_date);
"""

# Public sort key -> SQL expression. Priority sorts by rank, not alphabetically.
SORT_COLUMNS = {
    "created_at": "created_at",
    "due_date": "due_date IS NULL, due_date",  # tasks without a due date go last
    "priority": "CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END",
    "title": "title COLLATE NOCASE",
}


def connect(path: str) -> sqlite3.Connection:
    # check_same_thread=False: FastAPI may run the dependency and the endpoint on
    # different worker threads; each request still uses its connection serially.
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        status=Status(row["status"]),
        priority=Priority(row["priority"]),
        due_date=date.fromisoformat(row["due_date"]) if row["due_date"] else None,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


class TaskRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection

    def create(self, data: TaskCreate) -> Task:
        now = _now()
        with self._db:  # the with-block commits on success and rolls back on error
            cursor = self._db.execute(
                "INSERT INTO tasks (title, description, status, priority, due_date, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    data.title,
                    data.description,
                    data.status,
                    data.priority,
                    data.due_date.isoformat() if data.due_date else None,
                    now,
                    now,
                ),
            )
        task = self.get(cursor.lastrowid)
        assert task is not None
        return task

    def get(self, task_id: int) -> Task | None:
        row = self._db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _to_task(row) if row else None

    def list(
        self,
        *,
        status: Status | None = None,
        priority: Priority | None = None,
        search: str | None = None,
        sort: str = "created_at",
        descending: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Task], int]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if priority:
            clauses.append("priority = ?")
            params.append(priority)
        if search:
            clauses.append("(title LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\')")
            pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            params += [pattern, pattern]
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        total = self._db.execute(f"SELECT COUNT(*) FROM tasks {where}", params).fetchone()[0]
        order = SORT_COLUMNS[sort] + (" DESC" if descending else "")
        rows = self._db.execute(
            f"SELECT * FROM tasks {where} ORDER BY {order}, id LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return [_to_task(row) for row in rows], total

    def update(self, task_id: int, changes: TaskUpdate) -> Task | None:
        fields = changes.model_dump(exclude_unset=True)
        if not fields:
            return self.get(task_id)
        if "due_date" in fields and fields["due_date"] is not None:
            fields["due_date"] = fields["due_date"].isoformat()
        fields["updated_at"] = _now()
        # Column names come from the model's own field names, never from the request text.
        assignments = ", ".join(f"{column} = ?" for column in fields)
        with self._db:
            cursor = self._db.execute(
                f"UPDATE tasks SET {assignments} WHERE id = ?", [*fields.values(), task_id]
            )
        return self.get(task_id) if cursor.rowcount else None

    def delete(self, task_id: int) -> bool:
        with self._db:
            cursor = self._db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return cursor.rowcount > 0

    def stats(self, today: date) -> dict[str, Any]:
        counts = dict.fromkeys(Status, 0)
        for row in self._db.execute("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status"):
            counts[Status(row["status"])] = row["n"]
        overdue = self._db.execute(
            "SELECT COUNT(*) FROM tasks WHERE status != 'done' AND due_date < ?",
            (today.isoformat(),),
        ).fetchone()[0]
        return {"total": sum(counts.values()), "by_status": counts, "overdue": overdue}
