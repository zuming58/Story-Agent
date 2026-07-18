from __future__ import annotations

import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from test_phase5 import Phase5OpenAIHandler, derive_locked_contract, lock_canon, start_phase5_server
from test_phase7_automation import configure_automation_roles, update_policy, wait_for_run


def _create_trial_project(client: TestClient, title: str = "Trial Ready") -> dict:
    response = client.post("/api/v1/projects", json={"title": title, "mode": "long-form", "totalChapters": 20})
    assert response.status_code == 201, response.text
    return response.json()


def test_trial_readiness_is_read_only_and_reports_actionable_blockers(client: TestClient) -> None:
    project = _create_trial_project(client)
    project_id = project["id"]
    before_canon = client.get(f"/api/v1/projects/{project_id}/canon").json()
    before_policy = client.get(f"/api/v1/projects/{project_id}/automation/policy").json()

    response = client.get(f"/api/v1/projects/{project_id}/trial-readiness?chapterCount=3")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ready"] is False
    assert payload["startChapter"] == 1
    assert payload["endChapter"] == 3
    codes = {item["code"] for item in payload["checks"]}
    assert "TRIAL_MODEL_ROLE_MISSING" in codes
    assert "TRIAL_CANON_NOT_LOCKED" in codes
    assert all(item["actionPath"].startswith("/") for item in payload["checks"] if item["status"] == "blocked")

    after_canon = client.get(f"/api/v1/projects/{project_id}/canon").json()
    after_policy = client.get(f"/api/v1/projects/{project_id}/automation/policy").json()
    assert before_canon == after_canon
    assert before_policy["revision"] == after_policy["revision"]
    assert before_policy["enabled"] == after_policy["enabled"]
    assert before_policy["chaptersPerRun"] == after_policy["chaptersPerRun"]
    invalid = client.get(f"/api/v1/projects/{project_id}/trial-readiness?chapterCount=2")
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "TRIAL_CHAPTER_COUNT_INVALID"


def test_connection_test_is_persisted_and_provider_edits_invalidate_it(client: TestClient) -> None:
    server, base_url = start_phase5_server()
    try:
        # The Phase 5 fake only needs a deterministic /models response for this test.
        def do_get(handler: Phase5OpenAIHandler) -> None:
            body = json.dumps({"data": [{"id": "phase5-fake-model"}]}).encode("utf-8")
            handler.send_response(200)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)

        server.RequestHandlerClass.do_GET = do_get  # type: ignore[attr-defined]
        provider = client.post("/api/v1/model-providers", json={
            "name": "Connection Audit", "baseUrl": base_url, "apiKey": "unit-phase5-secret",
        }).json()
        tested = client.post(f"/api/v1/model-providers/{provider['id']}/test")
        assert tested.status_code == 200 and tested.json()["status"] == "success"
        persisted = client.get(f"/api/v1/model-providers/{provider['id']}").json()
        assert persisted["lastTestStatus"] == "success"
        assert persisted["lastTestedAt"]

        edited = client.patch(f"/api/v1/model-providers/{provider['id']}", json={"timeoutSeconds": 6})
        assert edited.status_code == 200
        assert edited.json()["lastTestStatus"] is None
        assert edited.json()["lastTestedAt"] is None
    finally:
        server.shutdown()
        server.server_close()


def test_readiness_reports_missing_key_and_prices_when_cost_guard_is_enabled(client: TestClient) -> None:
    project = _create_trial_project(client, "Readiness Guards")
    provider = client.post("/api/v1/model-providers", json={
        "name": "No Secret Provider", "baseUrl": "https://models.invalid.test",
    }).json()
    model = client.post(f"/api/v1/model-providers/{provider['id']}/models", json={
        "modelId": "unpriced-model", "displayName": "Unpriced Model",
    }).json()
    for role in ["chinese_writer", "fact_extractor", "continuity_reviewer", "story_editor", "style_reviewer", "reviser"]:
        assert client.put(f"/api/v1/model-role-bindings/{role}", json={"modelId": model["id"]}).status_code == 200
    update_policy(client, project["id"], dailyCostLimit=1.0)

    result = client.get(f"/api/v1/projects/{project['id']}/trial-readiness?chapterCount=1")
    assert result.status_code == 200
    codes = {item["code"] for item in result.json()["checks"]}
    assert "TRIAL_MODEL_UNAVAILABLE" in codes
    assert "TRIAL_MODEL_PRICE_MISSING" in codes


def test_active_chapter_job_blocks_only_its_own_project(client: TestClient) -> None:
    first = _create_trial_project(client, "Conflict Owner")
    second = _create_trial_project(client, "Isolated Neighbor")
    lock_canon(client, first["id"])
    contract = derive_locked_contract(client, first["id"])
    created = client.post(f"/api/v1/projects/{first['id']}/chapter-jobs", json={"chapterContractId": contract["id"]})
    assert created.status_code == 201, created.text

    first_codes = {item["code"] for item in client.get(
        f"/api/v1/projects/{first['id']}/trial-readiness?chapterCount=1"
    ).json()["checks"]}
    second_codes = {item["code"] for item in client.get(
        f"/api/v1/projects/{second['id']}/trial-readiness?chapterCount=1"
    ).json()["checks"]}
    assert "TRIAL_CHAPTER_JOB_CONFLICT" in first_codes
    assert "TRIAL_CHAPTER_JOB_CONFLICT" not in second_codes


def test_readiness_requires_per_chapter_beats_and_ignores_cancelled_jobs(client: TestClient) -> None:
    project = _create_trial_project(client, "Beat Guards")
    project_id = project["id"]
    window = client.post(f"/api/v1/projects/{project_id}/plan/nodes", json={
        "title": "Five chapter window",
        "type": "故事弧",
        "targetChapter": 1,
        "rangeMin": 1,
        "rangeMax": 5,
        "importance": 5,
        "prerequisites": ["Story begins"],
        "completionConditions": ["Window is complete"],
        "chapterBeats": [{
            "chapterNumber": 1,
            "title": "First beat",
            "objective": "Advance only the first local goal",
        }],
    })
    assert window.status_code == 201, window.text
    readiness = client.get(f"/api/v1/projects/{project_id}/trial-readiness?chapterCount=3").json()
    missing = next(item for item in readiness["checks"] if item["code"] == "TRIAL_CHAPTER_BEAT_MISSING")
    codes = {item["code"] for item in readiness["checks"]}
    assert readiness["ready"] is False
    assert "TRIAL_PLAN_READY" not in codes
    assert missing["status"] == "blocked"
    assert missing["chapterNumber"] == 2

    lock_canon(client, project_id)
    contract = client.post(f"/api/v1/projects/{project_id}/chapter-contracts/derive", json={
        "chapterNumber": 1,
        "planNodeId": window.json()["id"],
    }).json()
    locked = client.post(f"/api/v1/projects/{project_id}/chapter-contracts/{contract['id']}/lock", json={
        "expectedRevision": contract["revision"],
    }).json()
    job = client.post(f"/api/v1/projects/{project_id}/chapter-jobs", json={
        "chapterContractId": locked["id"],
    }).json()
    cancelled = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/cancel")
    assert cancelled.status_code == 200
    codes = {item["code"] for item in client.get(
        f"/api/v1/projects/{project_id}/trial-readiness?chapterCount=1"
    ).json()["checks"]}
    assert "TRIAL_CHAPTER_JOB_CONFLICT" not in codes


def test_manual_trial_sizes_one_and_five_are_validated_and_frozen(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _create_trial_project(client, "Frozen Trial Sizes")
    service = client.app.state.story_service
    monkeypatch.setattr(service.phase7, "dispatch_run", lambda _project_id, _run_id: None)

    one = client.post(f"/api/v1/projects/{project['id']}/automation/runs", json={
        "idempotencyKey": "trial-one", "chapterCount": 1,
    })
    five = client.post(f"/api/v1/projects/{project['id']}/automation/runs", json={
        "idempotencyKey": "trial-five", "chapterCount": 5,
    })
    invalid = client.post(f"/api/v1/projects/{project['id']}/automation/runs", json={
        "idempotencyKey": "trial-two", "chapterCount": 2,
    })
    assert one.status_code == 201 and one.json()["requestedChapterCount"] == 1
    assert five.status_code == 201 and five.json()["requestedChapterCount"] == 5
    assert one.json()["status"] == five.json()["status"] == "queued"
    assert invalid.status_code == 422
    with sqlite3.connect(f"{project['folderPath']}/story.db") as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "update automation_runs set requested_chapter_count = 2 where id = ?",
                (one.json()["id"],),
            )


def test_trial_batch_override_is_frozen_and_runs_three_chapters(client: TestClient) -> None:
    project = _create_trial_project(client, "Three Chapter Trial")
    project_id = project["id"]
    plan = client.get(f"/api/v1/projects/{project_id}/plan").json()
    node = plan["milestones"][0]
    simplified = client.patch(f"/api/v1/projects/{project_id}/plan/nodes/{node['id']}", json={
        "expectedRevision": node["revision"],
        "completionConditions": ["Lin Mo pushed open the old house door."],
        "contracts": ["A cold clue waited under the lamp."],
        "foreshadows": [],
        "chapterBeats": [
            {
                "chapterNumber": chapter,
                "title": f"Beat {chapter}",
                "objective": f"Advance chapter {chapter} only",
            }
            for chapter in range(1, 6)
        ],
    })
    assert simplified.status_code == 200, simplified.text
    lock_canon(client, project_id)
    server, base_url = start_phase5_server()
    try:
        def do_get(handler: Phase5OpenAIHandler) -> None:
            body = json.dumps({"data": [{"id": "phase5-fake-model"}]}).encode("utf-8")
            handler.send_response(200)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)

        server.RequestHandlerClass.do_GET = do_get  # type: ignore[attr-defined]
        configure_automation_roles(client, base_url, priced=True)
        provider = next(item for item in client.get("/api/v1/model-providers").json() if item["name"] == "Automation Fake")
        assert client.post(f"/api/v1/model-providers/{provider['id']}/test").json()["ok"] is True
        update_policy(client, project_id, chaptersPerRun=1)

        ready = client.get(f"/api/v1/projects/{project_id}/trial-readiness?chapterCount=3")
        assert ready.status_code == 200, ready.text
        assert ready.json()["ready"] is True
        assert ready.json()["maxSafeChapterCount"] == 5

        created = client.post(f"/api/v1/projects/{project_id}/automation/runs", json={
            "idempotencyKey": "trial-three", "chapterCount": 3,
        })
        assert created.status_code == 201, created.text
        run = wait_for_run(client, project_id, created.json()["id"])
        assert run["status"] == "completed", json.dumps(run, ensure_ascii=False)
        assert run["requestedChapterCount"] == 3
        assert run["plannedCount"] == 3
        assert run["succeededCount"] == 3
        assert [item["chapterNumber"] for item in run["items"]] == [1, 2, 3]

        duplicate = client.post(f"/api/v1/projects/{project_id}/automation/runs", json={
            "idempotencyKey": "trial-three", "chapterCount": 5,
        })
        assert duplicate.status_code == 201
        assert duplicate.json()["id"] == run["id"]
        assert duplicate.json()["requestedChapterCount"] == 3
        assert client.get(f"/api/v1/projects/{project_id}").json()["currentChapter"] == 3
    finally:
        server.shutdown()
        server.server_close()
