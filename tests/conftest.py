"""Shared fixtures: every test gets its own SQLite file and a pinned "today"."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from task_api.main import app, today

FIXED_TODAY = date(2026, 9, 15)


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("TASK_API_DB", str(tmp_path / "test.db"))
    app.dependency_overrides[today] = lambda: FIXED_TODAY
    with TestClient(app) as test_client:  # the with-block runs the lifespan (schema setup)
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def make_task(client):
    def _make(**fields) -> dict:
        payload = {"title": "Task"} | fields
        response = client.post("/tasks", json=payload)
        assert response.status_code == 201, response.text
        return response.json()

    return _make
