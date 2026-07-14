from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from story_agent_api.config import Settings
from story_agent_api.main import create_app


def test_projects_are_isolated_and_survive_restart(client: TestClient, demo_project: dict, data_dir: Path) -> None:
    created = client.post("/api/v1/projects", json={"title": "第二部作品", "mode": "short-form", "totalChapters": 30})
    assert created.status_code == 201
    second = created.json()
    assert second["id"] != demo_project["id"]
    assert second["folderPath"] != demo_project["folderPath"]
    assert Path(second["folderPath"], "story.db").exists()
    assert Path(demo_project["folderPath"], "story.db").exists()

    second_plan = client.get(f"/api/v1/projects/{second['id']}/plan").json()
    demo_plan = client.get(f"/api/v1/projects/{demo_project['id']}/plan").json()
    assert second_plan["milestones"][0]["title"] == "故事开端"
    assert demo_plan["milestones"][0]["title"] == "收到旧宅来信"

    restart_app = create_app(Settings(data_dir=data_dir, seed_demo=True))
    with TestClient(restart_app) as restarted:
        ids = {project["id"] for project in restarted.get("/api/v1/projects").json()}
        assert {demo_project["id"], second["id"]}.issubset(ids)


def test_plan_revision_conflict(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    node = client.get(f"/api/v1/projects/{project_id}/plan").json()["milestones"][1]
    payload = {"expectedRevision": node["revision"], "targetChapter": 19}
    updated = client.patch(f"/api/v1/projects/{project_id}/plan/nodes/{node['id']}", json=payload)
    assert updated.status_code == 200
    assert updated.json()["revision"] == node["revision"] + 1

    stale = client.patch(f"/api/v1/projects/{project_id}/plan/nodes/{node['id']}", json=payload)
    assert stale.status_code == 409
    assert stale.json()["code"] == "REVISION_CONFLICT"


def test_plan_window_can_be_created_and_persisted(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    response = client.post(f"/api/v1/projects/{project_id}/plan/nodes", json={
        "title": "档案馆调查期",
        "type": "章节窗口",
        "targetChapter": 37,
        "rangeMin": 22,
        "rangeMax": 42,
        "importance": 3,
        "note": "连接纸人初遇与第 45 章转折。",
        "prerequisites": ["完成首次纸人接触"],
        "completionConditions": ["获得北水塔入口"],
        "foreshadows": ["第四声铜铃"],
        "contracts": ["不得提前揭示纸童身份"],
        "pace": "smooth",
    })
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["revision"] == 1
    assert created["rangeMin"] == 22
    assert created["rangeMax"] == 42
    plan = client.get(f"/api/v1/projects/{project_id}/plan").json()
    assert any(item["id"] == created["id"] for item in plan["milestones"])
