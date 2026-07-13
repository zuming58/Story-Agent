from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from story_agent_api.models import AutomationRun, AutomationRunItem

from test_phase5 import configure_phase5_roles, lock_canon, start_phase5_server


def configure_automation_roles(client: TestClient, base_url: str, *, priced: bool = True) -> None:
    provider = client.post("/api/v1/model-providers", json={
        "name": "Automation Fake",
        "baseUrl": base_url,
        "timeoutSeconds": 5,
        "maxRetries": 0,
        "apiKey": "unit-phase5-secret",
    }).json()
    model_payload = {
        "modelId": "phase5-fake-model",
        "displayName": "Automation Fake",
    }
    if priced:
        model_payload["inputPricePerMillion"] = 1.0
        model_payload["outputPricePerMillion"] = 2.0
    model = client.post(f"/api/v1/model-providers/{provider['id']}/models", json=model_payload).json()
    for role in ["chinese_writer", "fact_extractor", "continuity_reviewer", "story_editor", "style_reviewer", "reviser"]:
        response = client.put(f"/api/v1/model-role-bindings/{role}", json={"modelId": model["id"]})
        assert response.status_code == 200, response.text


def wait_for_run(client: TestClient, project_id: str, run_id: str) -> dict:
    for _ in range(80):
        run = client.get(f"/api/v1/projects/{project_id}/automation/runs/{run_id}").json()
        if run["status"] in {"completed", "partial", "blocked", "failed", "cancelled", "missed", "interrupted"}:
            return run
        import time

        time.sleep(0.1)
    raise AssertionError("automation run did not finish")


def test_policy_update_revision_and_manual_run_idempotency(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    policy = client.get(f"/api/v1/projects/{project_id}/automation/policy")
    assert policy.status_code == 200, policy.text
    assert policy.json()["enabled"] is False
    stale = client.put(f"/api/v1/projects/{project_id}/automation/policy", json={
        "expectedRevision": policy.json()["revision"] + 1,
        "enabled": True,
        "timeOfDay": "03:00",
        "timezone": "UTC",
        "chaptersPerRun": 1,
        "targetWordsMin": 5,
        "targetWordsMax": 100,
        "maxRevisionRounds": 2,
        "dailyCostLimit": None,
        "stopPolicy": "stop_on_blocking",
        "approvalMode": "guarded_auto",
    })
    assert stale.status_code == 409
    updated = client.put(f"/api/v1/projects/{project_id}/automation/policy", json={
        "expectedRevision": policy.json()["revision"],
        "enabled": True,
        "timeOfDay": "03:00",
        "timezone": "Asia/Shanghai",
        "chaptersPerRun": 1,
        "targetWordsMin": 5,
        "targetWordsMax": 100,
        "maxRevisionRounds": 2,
        "dailyCostLimit": None,
        "stopPolicy": "stop_on_blocking",
        "approvalMode": "guarded_auto",
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["nextRunAt"]

    first = client.post(f"/api/v1/projects/{project_id}/automation/runs", json={"idempotencyKey": "same-run"})
    second = client.post(f"/api/v1/projects/{project_id}/automation/runs", json={"idempotencyKey": "same-run"})
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]


def test_automation_runs_one_chapter_through_guarded_commit(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    server, base_url = start_phase5_server()
    try:
        configure_automation_roles(client, base_url, priced=True)
        policy = client.get(f"/api/v1/projects/{project_id}/automation/policy").json()
        updated = client.put(f"/api/v1/projects/{project_id}/automation/policy", json={
            "expectedRevision": policy["revision"],
            "enabled": False,
            "timeOfDay": "03:00",
            "timezone": "UTC",
            "chaptersPerRun": 1,
            "targetWordsMin": 5,
            "targetWordsMax": 100,
            "maxRevisionRounds": 2,
            "dailyCostLimit": 1.0,
            "stopPolicy": "stop_on_blocking",
            "approvalMode": "guarded_auto",
        })
        assert updated.status_code == 200, updated.text
        created = client.post(f"/api/v1/projects/{project_id}/automation/runs", json={"idempotencyKey": "chapter-one"})
        assert created.status_code == 201, created.text
        run = wait_for_run(client, project_id, created.json()["id"])
        assert run["status"] == "completed"
        assert run["plannedCount"] == 1
        assert run["succeededCount"] == 1
        assert run["items"][0]["status"] == "committed"
        assert run["items"][0]["chapterCommitId"]
        assert run["totalTokens"] > 0
        assert run["estimatedCost"] > 0
        project = client.get(f"/api/v1/projects/{project_id}").json()
        assert project["currentChapter"] >= 1
    finally:
        server.shutdown()
        server.server_close()


def test_daily_cost_limit_requires_model_prices(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    server, base_url = start_phase5_server()
    try:
        configure_phase5_roles(client, base_url, reviewers=True, reviser=True)
        policy = client.get(f"/api/v1/projects/{project_id}/automation/policy").json()
        updated = client.put(f"/api/v1/projects/{project_id}/automation/policy", json={
            "expectedRevision": policy["revision"],
            "enabled": False,
            "timeOfDay": "03:00",
            "timezone": "UTC",
            "chaptersPerRun": 1,
            "targetWordsMin": 5,
            "targetWordsMax": 100,
            "maxRevisionRounds": 2,
            "dailyCostLimit": 1.0,
            "stopPolicy": "stop_on_blocking",
            "approvalMode": "guarded_auto",
        })
        assert updated.status_code == 200
        run = client.post(f"/api/v1/projects/{project_id}/automation/runs", json={})
        assert run.status_code == 409
        assert run.json()["code"] == "AUTOMATION_MODEL_PRICE_REQUIRED"
    finally:
        server.shutdown()
        server.server_close()


def test_missed_run_and_catch_up_use_same_executor(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    server, base_url = start_phase5_server()
    try:
        configure_automation_roles(client, base_url, priced=True)
        service = client.app.state.story_service
        project = service.get_project(project_id)
        policy = client.get(f"/api/v1/projects/{project_id}/automation/policy").json()
        updated = client.put(f"/api/v1/projects/{project_id}/automation/policy", json={
            "expectedRevision": policy["revision"],
            "enabled": True,
            "timeOfDay": "03:00",
            "timezone": "UTC",
            "chaptersPerRun": 1,
            "targetWordsMin": 5,
            "targetWordsMax": 100,
            "maxRevisionRounds": 2,
            "dailyCostLimit": 1.0,
            "stopPolicy": "stop_on_blocking",
            "approvalMode": "guarded_auto",
        })
        assert updated.status_code == 200
        with service.db.project_write(project.id, project.folder_path) as session:
            row = service.phase7._get_or_create_policy(session, project.id)
            row.next_run_at = datetime.now(timezone.utc) - timedelta(days=1)
        missed_ids = service.phase7.check_due_policies(execute_due=False)
        assert missed_ids
        missed = client.get(f"/api/v1/projects/{project_id}/automation/runs/{missed_ids[0]}").json()
        assert missed["status"] == "missed"
        caught = client.post(f"/api/v1/projects/{project_id}/automation/runs/{missed['id']}/catch-up")
        assert caught.status_code == 200, caught.text
        completed = wait_for_run(client, project_id, caught.json()["id"])
        assert completed["trigger"] == "catch_up"
        assert completed["status"] == "completed"
    finally:
        server.shutdown()
        server.server_close()


def test_startup_recovery_marks_running_automation_interrupted(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    service = client.app.state.story_service
    project = service.get_project(project_id)
    with service.db.project_write(project.id, project.folder_path) as session:
        policy = service.phase7._get_or_create_policy(session, project.id)
        run = AutomationRun(
            id="running-automation",
            project_id=project.id,
            policy_id=project.id,
            scheduled_local_date="2026-07-13",
            trigger="manual",
            status="running",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        item = AutomationRunItem(
            id="running-item",
            project_id=project.id,
            automation_run_id=run.id,
            chapter_number=1,
            sequence_number=1,
            status="running",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(policy)
        session.add(run)
        session.add(item)
    service.phase7.recover_interrupted_automation()
    recovered = client.get(f"/api/v1/projects/{project_id}/automation/runs/running-automation").json()
    assert recovered["status"] == "interrupted"
    assert recovered["items"][0]["status"] == "interrupted"


def test_automation_backup_restore_remaps_project_id(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    policy = client.get(f"/api/v1/projects/{project_id}/automation/policy").json()
    assert client.put(f"/api/v1/projects/{project_id}/automation/policy", json={
        "expectedRevision": policy["revision"],
        "enabled": False,
        "timeOfDay": "03:00",
        "timezone": "UTC",
        "chaptersPerRun": 1,
        "targetWordsMin": 5,
        "targetWordsMax": 100,
        "maxRevisionRounds": 2,
        "dailyCostLimit": None,
        "stopPolicy": "stop_on_blocking",
        "approvalMode": "guarded_auto",
    }).status_code == 200
    run = client.post(f"/api/v1/projects/{project_id}/automation/runs", json={"idempotencyKey": "backup-run"}).json()
    backup = client.post(f"/api/v1/projects/{project_id}/backups").json()
    archive = Path(backup["archivePath"])
    restored = client.post("/api/v1/projects/restore", files={"backup": (archive.name, archive.read_bytes(), "application/zip")})
    assert restored.status_code == 201, restored.text
    restored_id = restored.json()["id"]
    restored_policy = client.get(f"/api/v1/projects/{restored_id}/automation/policy").json()
    assert restored_policy["projectId"] == restored_id
    restored_runs = client.get(f"/api/v1/projects/{restored_id}/automation/runs").json()
    assert restored_runs
    assert restored_runs[0]["projectId"] == restored_id
    assert restored_runs[0]["id"] == run["id"]
