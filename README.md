# Task API (FastAPI + SQLite)

[![CI](https://github.com/Nexude-ZainaV/python-task-api/actions/workflows/ci.yml/badge.svg)](https://github.com/Nexude-ZainaV/python-task-api/actions/workflows/ci.yml)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Ruff](https://img.shields.io/badge/lint-ruff-D7FF64)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

A task tracker REST API. You can create, update, filter, search, sort and page through
tasks, and a stats endpoint reports an overdue count. FastAPI does the routing,
validation and OpenAPI docs. For storage I kept to plain `sqlite3` behind a small
repository class.

## Endpoints

| Method | Route | Description |
|---|---|---|
| `POST` | `/tasks` | Create a task (`201` + `Location` header) |
| `GET` | `/tasks` | List with `status`, `priority`, `q` (search), `sort`, `desc`, `limit`, `offset` |
| `GET` | `/tasks/stats` | Totals per status and the number of overdue tasks |
| `GET` | `/tasks/{id}` | One task, or `404` |
| `PATCH` | `/tasks/{id}` | Partial update: only the fields you send change |
| `DELETE` | `/tasks/{id}` | `204`, or `404` |
| `GET` | `/health` | Liveness check |

Interactive docs are generated at `/docs` (Swagger UI) and `/redoc`.

```bash
curl -X POST localhost:8000/tasks -H "Content-Type: application/json" \
     -d '{"title": "Ship v1", "priority": "high", "due_date": "2026-10-01"}'

curl "localhost:8000/tasks?status=todo&sort=priority&limit=10"
```

## Design notes

The code is in three layers: `models.py` (Pydantic schemas), `repository.py` (SQL) and
`main.py` (HTTP). Routes never touch SQL, and the repository never touches HTTP.

`get_repository` is a FastAPI dependency that opens one connection per request and
always closes it. The tests use `app.dependency_overrides` to swap `today()` for a
fixed date.

Every value goes into SQL as a `?` parameter. `ORDER BY` can't take parameters, so sort
keys are checked against an allow-list (`Literal[...]`) and mapped to fixed SQL. `LIKE`
wildcards in search text are escaped, so `100%` matches literally.

Pydantic rejects unknown fields (`extra="forbid"`), blank titles, bad enum values and
bad dates with a `422` and a per-field error body.

PATCH uses `model_dump(exclude_unset=True)`. Fields you leave out stay as they are, and
an explicit `null` clears a nullable field such as `due_date`.

The schema has `CHECK` constraints on the enum columns and an index on
`(status, due_date)` for the overdue query.

## Run it

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
fastapi dev src/task_api/main.py   # http://localhost:8000/docs
```

The database file defaults to `tasks.db`; set `TASK_API_DB` to change it.

The same checks CI runs:

```bash
ruff check . && ruff format --check .
pytest
```

## Project layout

```
src/task_api/
  main.py         app, routes, dependencies
  models.py       request/response schemas and enums
  repository.py   schema and parameterised SQL
tests/
  conftest.py     isolated database + fixed date per test
  test_tasks.py   HTTP-level tests
```

## License

[MIT](LICENSE)
