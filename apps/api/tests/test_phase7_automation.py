from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading

from fastapi.testclient import TestClient
from sqlalchemy import select
from story_agent_api.models import AutomationLease, AutomationRun, AutomationRunItem, ChapterContract, ChapterJob, ModelRun
from story_agent_api.model_provider import ModelProviderError
from story_agent_api.schemas import ChapterContractDerive, ChapterContractLock, ChapterJobCreate, ChapterJobRun

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


def update_policy(client: TestClient, project_id: str, **overrides: object) -> dict:
    policy = client.get(f"/api/v1/projects/{project_id}/automation/policy").json()
    payload = {
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
    }
    payload.update(overrides)
    response = client.put(f"/api/v1/projects/{project_id}/automation/policy", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


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
        missed_after = client.get(f"/api/v1/projects/{project_id}/automation/runs/{missed['id']}").json()
        assert missed_after["status"] == "missed"
        assert missed_after["diagnostic"]["catchUpRunId"] == completed["id"]
        repeated = client.post(f"/api/v1/projects/{project_id}/automation/runs/{missed['id']}/catch-up")
        assert repeated.status_code == 200
        assert repeated.json()["id"] == completed["id"]
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
    assert recovered["items"][0]["status"] == "waiting"


def test_startup_recovery_preserves_run_with_live_lease(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    service = client.app.state.story_service
    project = service.get_project(project_id)
    with service.db.project_write(project.id, project.folder_path) as session:
        policy = service.phase7._get_or_create_policy(session, project.id)
        run = service.phase7._create_run_row(session, policy, "manual", "2026-07-13", "live-lease-run", datetime.now(timezone.utc))
        run.status = "running"
        session.add(AutomationLease(
            project_id=project.id,
            owner_id=f"automation:{run.id}:other-process",
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            heartbeat_at=datetime.now(timezone.utc),
        ))
        run_id = run.id
    service.phase7.recover_interrupted_automation()
    preserved = client.get(f"/api/v1/projects/{project_id}/automation/runs/{run_id}").json()
    assert preserved["status"] == "running"
    with service.db.project(project.id, project.folder_path) as session:
        assert session.get(AutomationLease, project.id) is not None


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
    restored_reports = client.get(f"/api/v1/projects/{restored_id}/automation/reports")
    assert restored_reports.status_code == 200, restored_reports.text
    assert {report["projectId"] for report in restored_reports.json()} <= {restored_id}


def test_resume_reuses_persisted_candidate_without_second_writer_call(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    server, base_url = start_phase5_server()
    try:
        configure_automation_roles(client, base_url, priced=True)
        service = client.app.state.story_service
        project = service.get_project(project_id)
        contract = service.phase5.derive_chapter_contract(project_id, ChapterContractDerive(
            chapter_number=37,
            target_words_min=5,
            target_words_max=100,
        ), "resume-contract")
        contract = service.phase5.lock_chapter_contract(project_id, contract["id"], ChapterContractLock(
            expected_revision=contract["revision"],
        ), "resume-lock")
        job = service.phase5.create_chapter_job(project_id, ChapterJobCreate(
            chapter_contract_id=contract["id"],
            idempotency_key="pre-automation-job",
        ), "resume-job")
        service.phase5.run_chapter_job(project_id, job["id"], ChapterJobRun(), "resume-run")
        calls_before = server.RequestHandlerClass.post_count
        with service.db.project_write(project.id, project.folder_path) as session:
            row = session.get(ChapterJob, job["id"])
            row.status = "interrupted"
            row.error_code = "startup_recovery"
        update_policy(client, project_id)
        created = client.post(f"/api/v1/projects/{project_id}/automation/runs", json={"idempotencyKey": "resume-candidate"})
        completed = wait_for_run(client, project_id, created.json()["id"])
        assert completed["status"] == "completed"
        assert completed["items"][0]["chapterJobId"] == job["id"]
        assert server.RequestHandlerClass.post_count == calls_before
    finally:
        server.shutdown()
        server.server_close()


def test_daily_limit_counts_prior_runs_and_creates_report(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    server, base_url = start_phase5_server()
    try:
        configure_automation_roles(client, base_url, priced=True)
        update_policy(client, project_id, dailyCostLimit=1.0)
        service = client.app.state.story_service
        project = service.get_project(project_id)
        today = service.phase7._today_for_project(project.id, project.folder_path)
        with service.db.project_write(project.id, project.folder_path) as session:
            prior = AutomationRun(
                id="prior-daily-run",
                project_id=project.id,
                policy_id=project.id,
                scheduled_local_date=today,
                trigger="manual",
                status="completed",
                estimated_cost=0.999,
                created_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(prior)
            session.add(ModelRun(
                id="prior-daily-model-run",
                session_id=None,
                role="chinese_writer",
                model_id="phase5-fake-model",
                automation_run_id=prior.id,
                status="succeeded",
                estimated_cost=0.999,
                request_id="prior-cost",
                started_at=datetime.now(timezone.utc),
                ended_at=datetime.now(timezone.utc),
            ))
        created = client.post(f"/api/v1/projects/{project_id}/automation/runs", json={"idempotencyKey": "daily-budget"})
        blocked = wait_for_run(client, project_id, created.json()["id"])
        assert blocked["status"] == "blocked"
        assert blocked["stopReason"] == "AUTOMATION_COST_LIMIT_REACHED"
        assert server.RequestHandlerClass.post_count == 0
        reports = client.get(f"/api/v1/projects/{project_id}/automation/reports")
        assert reports.status_code == 200, reports.text
        assert reports.json()[0]["localDate"] == today
        assert reports.json()[0]["estimatedCost"] >= 0.999
    finally:
        server.shutdown()
        server.server_close()


def test_first_item_failure_skips_later_chapters_without_model_calls(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    update_policy(client, project_id, chaptersPerRun=2)
    created = client.post(f"/api/v1/projects/{project_id}/automation/runs", json={"idempotencyKey": "two-chapter-block"})
    blocked = wait_for_run(client, project_id, created.json()["id"])
    assert blocked["status"] == "blocked"
    assert [item["status"] for item in blocked["items"]] == ["isolated", "skipped"]
    assert blocked["items"][1]["chapterJobId"] is None
    assert client.get(f"/api/v1/projects/{project_id}/model-runs").json() == []


def test_lease_expiry_and_duplicate_dispatch_are_idempotent(client: TestClient, demo_project: dict, monkeypatch) -> None:
    project_id = demo_project["id"]
    service = client.app.state.story_service
    project = service.get_project(project_id)
    assert service.phase7._acquire_lease(project.id, project.folder_path, "owner-one") is True
    assert service.phase7._acquire_lease(project.id, project.folder_path, "owner-two") is False
    with service.db.project_write(project.id, project.folder_path) as session:
        lease = session.get(AutomationLease, project.id)
        lease.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert service.phase7._acquire_lease(project.id, project.folder_path, "owner-two") is True
    service.phase7._release_lease(project.id, project.folder_path, "owner-two")

    with service.db.project_write(project.id, project.folder_path) as session:
        row = service.phase7._get_or_create_policy(session, project.id)
        run = service.phase7._create_run_row(session, row, "manual", "2026-07-13", "dispatch-once", datetime.now(timezone.utc))
        run_id = run.id
    started = threading.Event()
    release = threading.Event()
    calls = {"count": 0}

    def controlled_execute(_project_id: str, _run_id: str) -> dict:
        calls["count"] += 1
        started.set()
        release.wait(timeout=5)
        return {}

    monkeypatch.setattr(service.phase7, "execute_run", controlled_execute)
    service.phase7.dispatch_run(project.id, run_id)
    assert started.wait(timeout=2)
    service.phase7.dispatch_run(project.id, run_id)
    release.set()
    for thread in list(service.phase7._running_threads.values()):
        thread.join(timeout=2)
    assert calls["count"] == 1


def test_active_run_heartbeats_lease_during_long_execution(client: TestClient, demo_project: dict, monkeypatch) -> None:
    project_id = demo_project["id"]
    service = client.app.state.story_service
    project = service.get_project(project_id)
    with service.db.project_write(project.id, project.folder_path) as session:
        policy = service.phase7._get_or_create_policy(session, project.id)
        run = service.phase7._create_run_row(session, policy, "manual", "2026-07-13", "heartbeat-run", datetime.now(timezone.utc))
        run_id = run.id
    heartbeats = {"count": 0}
    original_heartbeat = service.phase7._heartbeat

    def counted_heartbeat(project_id_arg: str, folder_path: str, owner_id: str) -> None:
        heartbeats["count"] += 1
        original_heartbeat(project_id_arg, folder_path, owner_id)

    monkeypatch.setattr("story_agent_api.phase7.LEASE_SECONDS", 0.15)
    monkeypatch.setattr(service.phase7, "_heartbeat", counted_heartbeat)
    monkeypatch.setattr(service.phase7, "_prepare_run", lambda *_args: __import__("time").sleep(0.25))
    result = service.phase7.execute_run(project.id, run_id)
    assert result["status"] == "completed"
    assert heartbeats["count"] >= 2


def test_two_chapters_are_serial_and_second_uses_new_snapshot(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    server, base_url = start_phase5_server()
    try:
        configure_automation_roles(client, base_url, priced=True)
        update_policy(client, project_id, chaptersPerRun=2)
        created = client.post(f"/api/v1/projects/{project_id}/automation/runs", json={"idempotencyKey": "two-serial"})
        completed = wait_for_run(client, project_id, created.json()["id"])
        assert completed["status"] == "completed"
        assert [item["status"] for item in completed["items"]] == ["committed", "committed"]
        service = client.app.state.story_service
        project = service.get_project(project_id)
        with service.db.project(project.id, project.folder_path) as session:
            first = session.get(ChapterContract, completed["items"][0]["chapterContractId"])
            second = session.get(ChapterContract, completed["items"][1]["chapterContractId"])
            assert first.state_snapshot_id is None
            assert second.state_snapshot_id is not None
            assert second.state_snapshot_id != first.state_snapshot_id
    finally:
        server.shutdown()
        server.server_close()


def test_automation_run_lease_budget_and_reports_are_project_isolated(client: TestClient, demo_project: dict) -> None:
    first_id = demo_project["id"]
    second = client.post("/api/v1/projects", json={
        "title": "Automation Isolation",
        "mode": "long-form",
        "totalChapters": 20,
    }).json()
    service = client.app.state.story_service
    first = service.get_project(first_id)
    second_project = service.get_project(second["id"])
    update_policy(client, first.id, dailyCostLimit=1.0)
    update_policy(client, second_project.id, dailyCostLimit=2.0)
    assert service.phase7._acquire_lease(first.id, first.folder_path, "first-owner") is True
    assert service.phase7._acquire_lease(second_project.id, second_project.folder_path, "second-owner") is True
    try:
        with service.db.project_write(first.id, first.folder_path) as session:
            policy = service.phase7._get_or_create_policy(session, first.id)
            first_run = service.phase7._create_run_row(session, policy, "manual", "2026-07-13", "first-isolation", datetime.now(timezone.utc))
            first_run.status = "completed"
        with service.db.project_write(second_project.id, second_project.folder_path) as session:
            policy = service.phase7._get_or_create_policy(session, second_project.id)
            second_run = service.phase7._create_run_row(session, policy, "manual", "2026-07-13", "second-isolation", datetime.now(timezone.utc))
            second_run.status = "completed"
        service.phase7._refresh_daily_report(first.id, first.folder_path, first_run.id)
        service.phase7._refresh_daily_report(second_project.id, second_project.folder_path, second_run.id)
        assert {run["id"] for run in client.get(f"/api/v1/projects/{first.id}/automation/runs").json()} == {first_run.id}
        assert {run["id"] for run in client.get(f"/api/v1/projects/{second_project.id}/automation/runs").json()} == {second_run.id}
        first_reports = client.get(f"/api/v1/projects/{first.id}/automation/reports").json()
        second_reports = client.get(f"/api/v1/projects/{second_project.id}/automation/reports").json()
        assert {report["projectId"] for report in first_reports} == {first.id}
        assert {report["projectId"] for report in second_reports} == {second_project.id}
    finally:
        service.phase7._release_lease(first.id, first.folder_path, "first-owner")
        service.phase7._release_lease(second_project.id, second_project.folder_path, "second-owner")


def test_consecutive_model_failure_threshold_blocks_second_attempt(client: TestClient, demo_project: dict, monkeypatch) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    server, base_url = start_phase5_server()
    try:
        configure_automation_roles(client, base_url, priced=True)
        update_policy(client, project_id, stopPolicy="stop_on_blocking")
        service = client.app.state.story_service

        async def fail_provider(*_args, **_kwargs):
            raise ModelProviderError("server_error", "injected provider failure", retryable=False)

        monkeypatch.setattr("story_agent_api.phase5.OpenAICompatibleModelProvider.complete_chat", fail_provider)
        first = client.post(f"/api/v1/projects/{project_id}/automation/runs", json={"idempotencyKey": "failure-threshold"})
        first_state = wait_for_run(client, project_id, first.json()["id"])
        assert first_state["status"] == "failed"
        assert first_state["diagnostic"]["consecutiveModelFailures"] == 1

        resumed = client.post(f"/api/v1/projects/{project_id}/automation/runs/{first_state['id']}/resume")
        assert resumed.status_code == 200, resumed.text
        second_state = wait_for_run(client, project_id, first_state["id"])
        assert second_state["status"] == "blocked"
        assert second_state["stopReason"] == "AUTOMATION_MODEL_FAILURE_THRESHOLD"
        assert second_state["diagnostic"]["consecutiveModelFailures"] == 2
        project = service.get_project(project_id)
        with service.db.project(project.id, project.folder_path) as session:
            runs = session.scalars(select(ModelRun).where(ModelRun.automation_run_id == first_state["id"])).all()
            assert [run.status for run in runs] == ["failed", "failed"]
    finally:
        server.shutdown()
        server.server_close()
