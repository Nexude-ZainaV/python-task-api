"""HTTP-level tests for the task endpoints. Run: pytest"""

from __future__ import annotations

import pytest


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_create_returns_201_location_and_defaults(client):
    response = client.post("/tasks", json={"title": "  Write README  "})

    assert response.status_code == 201
    body = response.json()
    assert response.headers["location"] == f"/tasks/{body['id']}"
    assert body["title"] == "Write README"
    assert body["status"] == "todo"
    assert body["priority"] == "medium"
    assert body["due_date"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": "   "},
        {"title": "x" * 121},
        {"title": "ok", "status": "blocked"},
        {"title": "ok", "due_date": "not-a-date"},
        {"title": "ok", "owner": "unexpected field"},
    ],
)
def test_create_rejects_invalid_payloads(client, payload):
    assert client.post("/tasks", json=payload).status_code == 422


def test_get_missing_task_is_404(client):
    response = client.get("/tasks/999")
    assert response.status_code == 404
    assert response.json()["detail"] == "task 999 not found"


def test_patch_changes_only_sent_fields(client, make_task):
    task = make_task(title="Draft", description="keep me", priority="low")

    response = client.patch(f"/tasks/{task['id']}", json={"status": "in_progress"})

    assert response.status_code == 200
    updated = response.json()
    assert updated["status"] == "in_progress"
    assert updated["description"] == "keep me"
    assert updated["priority"] == "low"


def test_patch_can_clear_due_date(client, make_task):
    task = make_task(due_date="2026-10-01")
    response = client.patch(f"/tasks/{task['id']}", json={"due_date": None})
    assert response.json()["due_date"] is None


def test_patch_missing_task_is_404(client):
    assert client.patch("/tasks/42", json={"title": "x"}).status_code == 404


def test_delete_then_404(client, make_task):
    task = make_task()
    assert client.delete(f"/tasks/{task['id']}").status_code == 204
    assert client.delete(f"/tasks/{task['id']}").status_code == 404


def test_list_filters_by_status_and_priority(client, make_task):
    make_task(title="a", status="done", priority="high")
    make_task(title="b", status="todo", priority="high")
    make_task(title="c", status="todo", priority="low")

    page = client.get("/tasks", params={"status": "todo", "priority": "high"}).json()

    assert page["total"] == 1
    assert [t["title"] for t in page["items"]] == ["b"]


def test_search_matches_title_or_description_case_insensitively(client, make_task):
    make_task(title="Fix login bug")
    make_task(title="Release", description="after the LOGIN fix")
    make_task(title="Unrelated")

    page = client.get("/tasks", params={"q": "login"}).json()
    assert page["total"] == 2


def test_search_treats_wildcards_literally(client, make_task):
    make_task(title="100% done")
    make_task(title="1000 items")

    page = client.get("/tasks", params={"q": "100%"}).json()
    assert [t["title"] for t in page["items"]] == ["100% done"]


def test_sort_by_priority_uses_rank_not_alphabet(client, make_task):
    make_task(title="low", priority="low")
    make_task(title="high", priority="high")
    make_task(title="medium", priority="medium")

    titles = [t["title"] for t in client.get("/tasks", params={"sort": "priority"}).json()["items"]]
    assert titles == ["high", "medium", "low"]


def test_sort_by_due_date_puts_undated_last(client, make_task):
    make_task(title="none")
    make_task(title="late", due_date="2026-12-01")
    make_task(title="soon", due_date="2026-09-20")

    titles = [t["title"] for t in client.get("/tasks", params={"sort": "due_date"}).json()["items"]]
    assert titles == ["soon", "late", "none"]


def test_unknown_sort_key_is_rejected(client):
    # The sort key is interpolated into ORDER BY, so only allow-listed values may pass.
    assert client.get("/tasks", params={"sort": "id; DROP TABLE tasks"}).status_code == 422


def test_pagination(client, make_task):
    for i in range(5):
        make_task(title=f"t{i}")

    page = client.get("/tasks", params={"limit": 2, "offset": 2}).json()

    assert page["total"] == 5
    assert [t["title"] for t in page["items"]] == ["t2", "t3"]
    assert client.get("/tasks", params={"limit": 0}).status_code == 422
    assert client.get("/tasks", params={"limit": 101}).status_code == 422


def test_stats_counts_statuses_and_overdue(client, make_task):
    make_task(status="done", due_date="2026-09-01")  # done: never overdue
    make_task(status="todo", due_date="2026-09-10")  # overdue (today is 2026-09-15)
    make_task(status="in_progress", due_date="2026-09-30")
    make_task(status="todo")

    stats = client.get("/tasks/stats").json()

    assert stats == {
        "total": 4,
        "by_status": {"todo": 2, "in_progress": 1, "done": 1},
        "overdue": 1,
    }
