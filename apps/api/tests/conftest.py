from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from story_agent_api.config import Settings
from story_agent_api.main import create_app


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "story-data"


@pytest.fixture
def client(data_dir: Path):
    app = create_app(Settings(data_dir=data_dir, seed_demo=True))
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def demo_project(client: TestClient) -> dict:
    response = client.get("/api/v1/projects")
    assert response.status_code == 200
    return response.json()[0]
