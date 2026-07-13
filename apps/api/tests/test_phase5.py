from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import story_agent_api.phase5 as phase5_module
from story_agent_api.model_provider import ModelStreamResult
from story_agent_api.models import ChapterCommit, ChapterJob, StateFact, SourceVersion
from story_agent_api.services import StoryError


class Phase5OpenAIHandler(BaseHTTPRequestHandler):
    post_count = 0
    invalid_extraction = False
    reviewer_truncations_remaining = 0
    observed_required_foreshadows: list[str] | None = None

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/chat/completions":
            self.send_response(404)
            self.end_headers()
            return
        type(self).post_count += 1
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else b"{}"
        request = json.loads(body.decode("utf-8"))
        if self.headers.get("Authorization") != "Bearer unit-phase5-secret":
            self.send_response(401)
            self.end_headers()
            return
        wants_json = request.get("response_format", {}).get("type") == "json_object"
        messages = request.get("messages", [])
        joined = "\n".join(str(item.get("content", "")) for item in messages if isinstance(item, dict))
        for message in messages:
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            try:
                user_payload = json.loads(str(message.get("content", "")))
            except (TypeError, ValueError):
                continue
            if user_payload.get("section") == "narrative":
                type(self).observed_required_foreshadows = user_payload.get("requiredForeshadows")
        finish_reason = "stop"
        if wants_json and type(self).invalid_extraction and "chapterMarkdown" in joined:
            content = "not-json"
        elif wants_json and "requiredOutput" in joined:
            content = json.dumps({"findings": []})
            if type(self).reviewer_truncations_remaining > 0:
                type(self).reviewer_truncations_remaining -= 1
                finish_reason = "length"
        elif wants_json and "contentMarkdown" in joined:
            content = json.dumps({"contentMarkdown": "Lin Mo pushed open the old house door. The required condition is now visible."})
        elif wants_json:
            content = json.dumps({
                "summary": "Lin Mo enters the old house.",
                "entities": [{
                    "entityTypeName": "person",
                    "canonicalName": "Lin Mo",
                    "aliases": ["LM"],
                    "attributes": {"name": "Lin Mo"},
                }],
                "facts": [{"entity": "Lin Mo", "fieldPath": "location", "value": "old house", "confidence": 0.9}],
                "events": [{"eventOrder": 1, "summary": "Lin Mo enters the old house.", "participants": ["Lin Mo"]}],
                "foreshadows": [],
                "boundaries": [{"entity": "Lin Mo", "knowledge": {"knows": ["old house"]}}],
            })
        else:
            content = "Lin Mo pushed open the old house door.\n\nA cold clue waited under the lamp."
        response = json.dumps({
            "model": "phase5-fake-model",
            "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *_args: object) -> None:
        return


def start_phase5_server(
    *, invalid_extraction: bool = False, reviewer_truncations: int = 0,
) -> tuple[ThreadingHTTPServer, str]:
    class Handler(Phase5OpenAIHandler):
        pass

    Handler.post_count = 0
    Handler.invalid_extraction = invalid_extraction
    Handler.reviewer_truncations_remaining = reviewer_truncations
    Handler.observed_required_foreshadows = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


def configure_phase5_roles(client: TestClient, base_url: str, *, reviewers: bool = False, reviser: bool = False) -> None:
    provider = client.post("/api/v1/model-providers", json={
        "name": "Phase 5 Fake",
        "baseUrl": base_url,
        "timeoutSeconds": 5,
        "maxRetries": 0,
        "apiKey": "unit-phase5-secret",
    }).json()
    model = client.post(f"/api/v1/model-providers/{provider['id']}/models", json={
        "modelId": "phase5-fake-model",
        "displayName": "Phase 5 Fake",
    }).json()
    roles = ["chinese_writer", "fact_extractor"]
    if reviewers:
        roles.extend(["continuity_reviewer", "story_editor", "style_reviewer"])
    if reviser:
        roles.append("reviser")
    for role in roles:
        response = client.put(f"/api/v1/model-role-bindings/{role}", json={"modelId": model["id"]})
        assert response.status_code == 200, response.text


def lock_canon(client: TestClient, project_id: str) -> None:
    root = client.get(f"/api/v1/projects/{project_id}/canon").json()["documents"][0]
    response = client.post(f"/api/v1/projects/{project_id}/canon/lock", json={"expectedRevision": root["revision"]})
    assert response.status_code == 200, response.text


def derive_locked_contract(client: TestClient, project_id: str) -> dict:
    node_id = client.get(f"/api/v1/projects/{project_id}/plan").json()["milestones"][0]["id"]
    derived = client.post(f"/api/v1/projects/{project_id}/chapter-contracts/derive", json={
        "chapterNumber": 1,
        "planNodeId": node_id,
        "targetWordsMin": 5,
        "targetWordsMax": 100,
    })
    assert derived.status_code == 200, derived.text
    contract = derived.json()
    locked = client.post(f"/api/v1/projects/{project_id}/chapter-contracts/{contract['id']}/lock", json={
        "expectedRevision": contract["revision"],
    })
    assert locked.status_code == 200, locked.text
    return locked.json()


def seed_official_state(client: TestClient, project_id: str, *, name: str, location: str, source_id: str) -> dict:
    entity_type = next(item for item in client.get(f"/api/v1/projects/{project_id}/canon").json()["entityTypes"] if item["name"] == "person")
    candidate = client.post(f"/api/v1/projects/{project_id}/state/candidates", json={
        "sourceId": source_id,
        "versionNumber": 1,
        "sourceKind": "manual",
        "entities": [{
            "entityTypeId": entity_type["id"],
            "canonicalName": name,
            "attributes": {"name": name},
        }],
        "facts": [{"entity": name, "fieldPath": "location", "value": location}],
        "events": [{"eventOrder": 1, "summary": f"{name} is at {location}."}],
    })
    assert candidate.status_code == 200, candidate.text
    committed = client.post(f"/api/v1/state/candidates/{candidate.json()['id']}/commit", json={
        "projectId": project_id,
        "expectedRevision": candidate.json()["revision"],
    })
    assert committed.status_code == 200, committed.text
    return committed.json()


def accept_open_blocking_findings(client: TestClient, project_id: str, job_id: str) -> None:
    quality = client.get(f"/api/v1/projects/{project_id}/chapter-jobs/{job_id}/quality").json()
    for finding in quality["findings"]:
        if finding["status"] == "open" and finding["severity"] in {"error", "blocker"}:
            accepted = client.post(f"/api/v1/projects/{project_id}/quality-findings/{finding['id']}/accept-risk", json={"reason": "explicit unit-test risk acceptance"})
            assert accepted.status_code == 200, accepted.text


def run_and_approve_job(client: TestClient, project_id: str) -> tuple[dict, dict, dict]:
    contract = derive_locked_contract(client, project_id)
    job = client.post(f"/api/v1/projects/{project_id}/chapter-jobs", json={"chapterContractId": contract["id"]}).json()
    run = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/run", json={})
    assert run.status_code == 200, run.text
    accept_open_blocking_findings(client, project_id, job["id"])
    state = client.get(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}").json()
    approved = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/approve", json={
        "mode": "manual",
        "expectedJobRevision": state["revision"],
    })
    assert approved.status_code == 200, approved.text
    return contract, job, approved.json()


def test_chapter_contract_lock_blocks_in_place_edits(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    contract = derive_locked_contract(client, project_id)

    edit = client.put(f"/api/v1/projects/{project_id}/chapter-contracts/{contract['id']}", json={
        "expectedRevision": contract["revision"],
        "title": "Rewrite in place",
    })
    assert edit.status_code == 409
    assert edit.json()["code"] == "CHAPTER_CONTRACT_LOCKED"
    listed = client.get(f"/api/v1/projects/{project_id}/chapter-contracts").json()
    assert listed[0]["status"] == "locked"


def test_chapter_window_derives_only_the_current_chapter_beat(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    window = client.post(f"/api/v1/projects/{project_id}/plan/nodes", json={
        "title": "Investigation window",
        "type": "章节窗口",
        "targetChapter": 37,
        "rangeMin": 37,
        "rangeMax": 41,
        "importance": 5,
        "prerequisites": ["Chapter 36 is official"],
        "completionConditions": ["The five-chapter window is complete"],
        "contracts": ["Advance only one local objective per chapter"],
        "chapterBeats": [
            {
                "chapterNumber": 37,
                "title": "Footprints in the map cabinet",
                "objective": "Follow the wet footprints and recover the clipped map.",
                "completionConditions": ["Recover the clipped map"],
                "hooks": ["A fourth bell rings"],
                "foreshadows": ["Mother's former surname"],
                "requiredCharacters": ["Shen Yan"],
                "forbidden": ["Identify the bell manipulator"],
            },
            {
                "chapterNumber": 38,
                "title": "The impossible fourth bell",
                "objective": "Prove the fourth bell was a human lure.",
                "completionConditions": ["Find evidence of a human lure"],
                "hooks": ["A duty log page is missing"],
                "requiredCharacters": ["Shen Yan", "Old Zhou"],
            },
        ],
    })
    assert window.status_code == 201, window.text

    chapter_37 = client.post(f"/api/v1/projects/{project_id}/chapter-contracts/derive", json={
        "chapterNumber": 37,
        "planNodeId": window.json()["id"],
    })
    assert chapter_37.status_code == 200, chapter_37.text
    first = chapter_37.json()
    assert first["title"] == "Footprints in the map cabinet"
    assert first["objective"]["mustAdvance"]["objective"] == "Follow the wet footprints and recover the clipped map."
    assert first["completionConditions"] == ["Recover the clipped map"]
    assert first["requiredCharacters"] == ["Shen Yan"]
    assert first["requiredHooks"] == ["A fourth bell rings"]
    assert "The five-chapter window is complete" not in first["completionConditions"]

    chapter_38 = client.post(f"/api/v1/projects/{project_id}/chapter-contracts/derive", json={
        "chapterNumber": 38,
        "planNodeId": window.json()["id"],
    })
    assert chapter_38.status_code == 200, chapter_38.text
    second = chapter_38.json()
    assert second["title"] == "The impossible fourth bell"
    assert second["completionConditions"] == ["Find evidence of a human lure"]
    assert second["requiredCharacters"] == ["Shen Yan", "Old Zhou"]

    missing = client.post(f"/api/v1/projects/{project_id}/chapter-contracts/derive", json={
        "chapterNumber": 39,
        "planNodeId": window.json()["id"],
    })
    assert missing.status_code == 409
    assert missing.json()["code"] == "CHAPTER_BEAT_MISSING"


def test_cancelled_job_allows_replacing_its_locked_contract(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    previous = derive_locked_contract(client, project_id)
    job = client.post(f"/api/v1/projects/{project_id}/chapter-jobs", json={
        "chapterContractId": previous["id"],
        "idempotencyKey": "abandoned-contract",
    }).json()
    cancelled = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    replacement = client.post(f"/api/v1/projects/{project_id}/chapter-contracts/derive", json={
        "chapterNumber": 1,
        "planNodeId": previous["planNodeId"],
    }).json()
    locked = client.post(f"/api/v1/projects/{project_id}/chapter-contracts/{replacement['id']}/lock", json={
        "expectedRevision": replacement["revision"],
    })
    assert locked.status_code == 200, locked.text
    contracts = client.get(f"/api/v1/projects/{project_id}/chapter-contracts").json()
    prior = next(item for item in contracts if item["id"] == previous["id"])
    assert prior["status"] == "superseded"


def test_chapter_job_idempotency_and_candidate_pipeline_do_not_commit_state(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    server, base_url = start_phase5_server()
    try:
        configure_phase5_roles(client, base_url)
        contract = derive_locked_contract(client, project_id)
        first = client.post(f"/api/v1/projects/{project_id}/chapter-jobs", json={
            "chapterContractId": contract["id"],
            "idempotencyKey": "chapter-1",
        })
        assert first.status_code == 201, first.text
        second = client.post(f"/api/v1/projects/{project_id}/chapter-jobs", json={
            "chapterContractId": contract["id"],
            "idempotencyKey": "chapter-1",
        })
        assert second.status_code == 201
        assert second.json()["id"] == first.json()["id"]

        run = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{first.json()['id']}/run", json={})
        assert run.status_code == 200, run.text
        assert run.json()["status"] == "human_review"
        drafts = client.get(f"/api/v1/projects/{project_id}/chapters/1/drafts").json()
        assert len(drafts) == 1
        assert drafts[0]["status"] == "candidate"
        detail = client.get(f"/api/v1/projects/{project_id}/chapter-drafts/{drafts[0]['id']}").json()
        assert detail["extraction"]["status"] == "validated"
        assert client.get(f"/api/v1/projects/{project_id}/state/entities").json() == []
        quality = client.get(f"/api/v1/projects/{project_id}/chapter-jobs/{first.json()['id']}/quality").json()
        assert any(item["ruleCode"] == "CHAPTER_MODEL_ROLE_NOT_CONFIGURED" for item in quality["findings"])
        runs = client.get(f"/api/v1/projects/{project_id}/model-runs").json()
        assert {"chinese_writer", "fact_extractor"}.issubset({item["role"] for item in runs})
    finally:
        server.shutdown()
        server.server_close()


def test_quality_accept_risk_and_revision_creates_new_draft(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    server, base_url = start_phase5_server()
    try:
        configure_phase5_roles(client, base_url, reviser=True)
        contract = derive_locked_contract(client, project_id)
        job = client.post(f"/api/v1/projects/{project_id}/chapter-jobs", json={"chapterContractId": contract["id"]}).json()
        assert client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/run", json={}).status_code == 200
        quality = client.get(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/quality").json()
        finding = next(item for item in quality["findings"] if item["ruleCode"] == "CHAPTER_MODEL_ROLE_NOT_CONFIGURED")
        accepted = client.post(f"/api/v1/projects/{project_id}/quality-findings/{finding['id']}/accept-risk", json={"reason": "unit test accepts missing reviewer"})
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "accepted_risk"

        revised = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/revise", json={"reason": "address accepted and open issues"})
        assert revised.status_code == 200, revised.text
        drafts = client.get(f"/api/v1/projects/{project_id}/chapters/1/drafts").json()
        assert len(drafts) == 2
        assert drafts[0]["parentDraftId"] == drafts[1]["id"]
    finally:
        server.shutdown()
        server.server_close()


def test_configured_reviewers_do_not_create_missing_role_findings(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    server, base_url = start_phase5_server()
    try:
        configure_phase5_roles(client, base_url, reviewers=True)
        contract = derive_locked_contract(client, project_id)
        job = client.post(f"/api/v1/projects/{project_id}/chapter-jobs", json={"chapterContractId": contract["id"]}).json()
        assert client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/run", json={}).status_code == 200
        quality = client.get(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/quality").json()
        assert all(item["ruleCode"] != "CHAPTER_MODEL_ROLE_NOT_CONFIGURED" for item in quality["findings"])
        reviewer_runs = [item for item in quality["runs"] if item["gateType"] == "model"]
        assert {item["reviewerRole"] for item in reviewer_runs} == {"continuity_reviewer", "story_editor", "style_reviewer"}
    finally:
        server.shutdown()
        server.server_close()


def test_approve_and_commit_materializes_chapter_state_and_mirror(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    server, base_url = start_phase5_server()
    try:
        configure_phase5_roles(client, base_url, reviewers=True)
        contract = derive_locked_contract(client, project_id)
        job = client.post(f"/api/v1/projects/{project_id}/chapter-jobs", json={"chapterContractId": contract["id"]}).json()
        run = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/run", json={})
        assert run.status_code == 200, run.text
        quality = client.get(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/quality").json()
        for finding in quality["findings"]:
            if finding["status"] == "open" and finding["severity"] in {"error", "blocker"}:
                accepted = client.post(f"/api/v1/projects/{project_id}/quality-findings/{finding['id']}/accept-risk", json={"reason": "manual approval for unit test"})
                assert accepted.status_code == 200, accepted.text
        job_state = client.get(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}").json()
        approved = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/approve", json={
            "mode": "manual",
            "expectedJobRevision": job_state["revision"],
        })
        assert approved.status_code == 200, approved.text
        committed = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/commit", json={
            "expectedJobRevision": approved.json()["revision"],
        })
        assert committed.status_code == 200, committed.text
        commit = committed.json()
        assert commit["status"] == "official"
        assert commit["sourceVersionId"]
        assert commit["stateSnapshotId"]
        entities = client.get(f"/api/v1/projects/{project_id}/state/entities").json()
        assert entities and entities[0]["canonicalName"] == "Lin Mo"
        project = client.get(f"/api/v1/projects/{project_id}").json()
        mirror_path = project["folderPath"] + "\\manuscripts\\chapter-0001.md"
        from pathlib import Path

        assert Path(mirror_path).exists()
        repeated = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/commit", json={
            "expectedJobRevision": approved.json()["revision"],
        })
        assert repeated.status_code == 200
        assert repeated.json()["id"] == commit["id"]
        cannot_cancel = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/cancel")
        assert cannot_cancel.status_code == 409
        assert cannot_cancel.json()["code"] == "CHAPTER_JOB_NOT_CANCELLABLE"

        backup = client.post(f"/api/v1/projects/{project_id}/backups").json()
        archive = Path(backup["archivePath"])
        restored = client.post("/api/v1/projects/restore", files={"backup": (archive.name, archive.read_bytes(), "application/zip")})
        assert restored.status_code == 201, restored.text
        restored_id = restored.json()["id"]
        restored_drafts = client.get(f"/api/v1/projects/{restored_id}/chapters/1/drafts").json()
        assert restored_drafts and restored_drafts[0]["contentMarkdown"]
        restored_project = client.get(f"/api/v1/projects/{restored_id}").json()
        assert Path(restored_project["folderPath"], "manuscripts", "chapter-0001.md").exists()
    finally:
        server.shutdown()
        server.server_close()


def test_contract_for_early_chapter_sets_up_future_milestone_without_consuming_it(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    node = client.get(f"/api/v1/projects/{project_id}/plan").json()["milestones"][0]
    derived = client.post(f"/api/v1/projects/{project_id}/chapter-contracts/derive", json={
        "chapterNumber": 1,
        "planNodeId": node["id"],
        "targetWordsMin": 10,
        "targetWordsMax": 100,
    })
    assert derived.status_code == 200, derived.text
    contract = derived.json()
    assert contract["objective"]["mustAdvance"]["setupForPlanNodeId"] == node["id"]
    assert contract["allowedScope"]["completionConditions"] == []
    assert contract["forbiddenScope"]["mustNotComplete"][0]["id"] == node["id"]

    out_of_range = client.post(f"/api/v1/projects/{project_id}/chapter-contracts/derive", json={"chapterNumber": demo_project["totalChapters"] + 1})
    assert out_of_range.status_code == 422
    assert out_of_range.json()["code"] == "CHAPTER_NUMBER_OUT_OF_RANGE"
    null_update = client.put(f"/api/v1/projects/{project_id}/chapter-contracts/{contract['id']}", json={
        "expectedRevision": contract["revision"],
        "objective": None,
    })
    assert null_update.status_code == 422
    assert null_update.json()["code"] == "INVALID_CHAPTER_CONTRACT"


def test_contract_lock_rejects_stale_plan_revision(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    node = client.get(f"/api/v1/projects/{project_id}/plan").json()["milestones"][0]
    contract = client.post(f"/api/v1/projects/{project_id}/chapter-contracts/derive", json={
        "chapterNumber": 1,
        "planNodeId": node["id"],
    }).json()
    updated = client.patch(f"/api/v1/projects/{project_id}/plan/nodes/{node['id']}", json={
        "expectedRevision": node["revision"],
        "note": "changed after contract derivation",
    })
    assert updated.status_code == 200, updated.text
    locked = client.post(f"/api/v1/projects/{project_id}/chapter-contracts/{contract['id']}/lock", json={"expectedRevision": contract["revision"]})
    assert locked.status_code == 409
    assert locked.json()["code"] == "CHAPTER_CONTEXT_STALE"


def test_state_conflict_is_a_deterministic_blocker_before_approval(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    seed_official_state(client, project_id, name="Lin Mo", location="street", source_id="preexisting-state")
    server, base_url = start_phase5_server()
    try:
        configure_phase5_roles(client, base_url, reviewers=True)
        contract = derive_locked_contract(client, project_id)
        job = client.post(f"/api/v1/projects/{project_id}/chapter-jobs", json={"chapterContractId": contract["id"]}).json()
        run = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/run", json={})
        assert run.status_code == 200, run.text
        quality = client.get(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/quality").json()
        conflict = next(item for item in quality["findings"] if item["ruleCode"] == "CHAPTER_STATE_CONFLICT")
        assert conflict["severity"] == "blocker"
        state = client.get(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}").json()
        approval = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/approve", json={
            "mode": "guarded_auto",
            "expectedJobRevision": state["revision"],
        })
        assert approval.status_code == 409
        assert approval.json()["code"] == "CHAPTER_QUALITY_BLOCKED"
    finally:
        server.shutdown()
        server.server_close()


def test_guarded_auto_cannot_use_accepted_risk_to_fake_missing_reviewers(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    server, base_url = start_phase5_server()
    try:
        configure_phase5_roles(client, base_url)
        contract = derive_locked_contract(client, project_id)
        job = client.post(f"/api/v1/projects/{project_id}/chapter-jobs", json={"chapterContractId": contract["id"]}).json()
        assert client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/run", json={}).status_code == 200
        accept_open_blocking_findings(client, project_id, job["id"])
        state = client.get(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}").json()
        approval = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/approve", json={
            "mode": "guarded_auto",
            "expectedJobRevision": state["revision"],
        })
        assert approval.status_code == 409
        assert set(approval.json()["details"]["missingReviewers"]) == {"continuity_reviewer", "story_editor", "style_reviewer"}
    finally:
        server.shutdown()
        server.server_close()


def test_failed_revision_preserves_open_findings_and_does_not_consume_round(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    server, base_url = start_phase5_server()
    try:
        configure_phase5_roles(client, base_url)
        contract = derive_locked_contract(client, project_id)
        job = client.post(f"/api/v1/projects/{project_id}/chapter-jobs", json={"chapterContractId": contract["id"]}).json()
        assert client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/run", json={}).status_code == 200
        before = client.get(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/quality").json()
        open_ids = {item["id"] for item in before["findings"] if item["status"] == "open"}
        revised = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/revise", json={"reason": "reviser is intentionally unconfigured"})
        assert revised.status_code == 409
        assert revised.json()["code"] == "CHAPTER_MODEL_ROLE_NOT_CONFIGURED"
        state = client.get(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}").json()
        assert state["status"] == "human_review"
        assert state["currentRevisionRound"] == 0
        after = client.get(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/quality").json()
        assert open_ids.issubset({item["id"] for item in after["findings"] if item["status"] == "open"})
    finally:
        server.shutdown()
        server.server_close()


def test_startup_recovery_and_retry_reset_job_timing(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    contract = derive_locked_contract(client, project_id)
    job = client.post(f"/api/v1/projects/{project_id}/chapter-jobs", json={"chapterContractId": contract["id"]}).json()
    service = client.app.state.story_service
    project = service.get_project(project_id)
    with service.db.project_write(project.id, project.folder_path) as session:
        row = session.get(ChapterJob, job["id"])
        row.status = "drafting"
        row.started_at = row.updated_at
    service.phase5.recover_interrupted_jobs()
    interrupted = client.get(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}").json()
    assert interrupted["status"] == "interrupted"
    retried = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/retry", json={"reason": "resume after restart"})
    assert retried.status_code == 200
    assert retried.json()["status"] == "queued"
    assert retried.json()["startedAt"] is None
    assert retried.json()["finishedAt"] is None


def test_phase5_project_namespaces_are_isolated(client: TestClient, demo_project: dict) -> None:
    first_id = demo_project["id"]
    second = client.post("/api/v1/projects", json={"title": "Phase Five Second", "mode": "long-form", "totalChapters": 100}).json()
    for project_id in (first_id, second["id"]):
        lock_canon(client, project_id)
    first_contract = derive_locked_contract(client, first_id)
    second_contract = derive_locked_contract(client, second["id"])
    first_job = client.post(f"/api/v1/projects/{first_id}/chapter-jobs", json={"chapterContractId": first_contract["id"], "idempotencyKey": "same-key"}).json()
    second_job = client.post(f"/api/v1/projects/{second['id']}/chapter-jobs", json={"chapterContractId": second_contract["id"], "idempotencyKey": "same-key"}).json()
    assert first_job["id"] != second_job["id"]
    assert {item["id"] for item in client.get(f"/api/v1/projects/{first_id}/chapter-jobs").json()} == {first_job["id"]}
    assert {item["id"] for item in client.get(f"/api/v1/projects/{second['id']}/chapter-jobs").json()} == {second_job["id"]}


def test_commit_rejects_stale_story_snapshot_and_persists_human_review(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    server, base_url = start_phase5_server()
    try:
        configure_phase5_roles(client, base_url, reviewers=True)
        _contract, job, approved = run_and_approve_job(client, project_id)
        seed_official_state(client, project_id, name="External Witness", location="station", source_id="state-after-approval")
        committed = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/commit", json={
            "expectedJobRevision": approved["revision"],
        })
        assert committed.status_code == 409
        assert committed.json()["code"] == "CHAPTER_CONTEXT_STALE"
        state = client.get(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}").json()
        assert state["status"] == "human_review"
        assert state["errorCode"] == "CHAPTER_CONTEXT_STALE"
    finally:
        server.shutdown()
        server.server_close()


def test_commit_failure_rolls_back_source_state_and_commit(client: TestClient, demo_project: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    server, base_url = start_phase5_server()
    try:
        configure_phase5_roles(client, base_url, reviewers=True)
        _contract, job, approved = run_and_approve_job(client, project_id)
        service = client.app.state.story_service

        def fail_materialization(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("injected materialization failure")

        monkeypatch.setattr(service.phase4, "_materialize_state_payload", fail_materialization)
        committed = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/commit", json={
            "expectedJobRevision": approved["revision"],
        })
        assert committed.status_code == 500
        assert committed.json()["code"] == "CHAPTER_COMMIT_FAILED"
        state = client.get(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}").json()
        assert state["status"] == "human_review"
        assert state["errorCode"] == "CHAPTER_COMMIT_FAILED"
        assert client.get(f"/api/v1/projects/{project_id}/state/entities").json() == []
        project = service.get_project(project_id)
        with service.db.project(project.id, project.folder_path) as session:
            chapter_sources = session.scalars(select(SourceVersion).where(SourceVersion.source_kind == "chapter")).all()
            assert chapter_sources == []
    finally:
        server.shutdown()
        server.server_close()


def test_canon_change_invalidates_unlocked_chapter_contract(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    node_id = client.get(f"/api/v1/projects/{project_id}/plan").json()["milestones"][0]["id"]
    contract = client.post(f"/api/v1/projects/{project_id}/chapter-contracts/derive", json={"chapterNumber": 1, "planNodeId": node_id}).json()
    change = client.post(f"/api/v1/projects/{project_id}/canon/change-requests", json={
        "projectId": project_id,
        "targetKind": "document",
        "targetId": "story-core",
        "reason": "change canon after contract derivation",
        "afterJson": {"title": "Changed Story Core"},
    })
    assert change.status_code == 200, change.text
    applied = client.post(f"/api/v1/canon/change-requests/{change.json()['id']}/apply", json={
        "projectId": project_id,
        "expectedRevision": change.json()["revision"],
    })
    assert applied.status_code == 200, applied.text
    locked = client.post(f"/api/v1/projects/{project_id}/chapter-contracts/{contract['id']}/lock", json={"expectedRevision": contract["revision"]})
    assert locked.status_code == 409
    assert locked.json()["code"] == "CHAPTER_CONTEXT_STALE"
    assert locked.json()["details"]["reason"] == "canon_revision_changed"


def test_invalid_extraction_repairs_once_and_never_touches_official_state(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    server, base_url = start_phase5_server(invalid_extraction=True)
    try:
        configure_phase5_roles(client, base_url)
        contract = derive_locked_contract(client, project_id)
        job = client.post(f"/api/v1/projects/{project_id}/chapter-jobs", json={"chapterContractId": contract["id"]}).json()
        run = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/run", json={})
        assert run.status_code == 422
        assert run.json()["code"] == "CHAPTER_EXTRACTION_INVALID"
        assert server.RequestHandlerClass.post_count == 3, "one writer call plus exactly two extraction attempts"
        assert client.get(f"/api/v1/projects/{project_id}/state/entities").json() == []
        state = client.get(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}").json()
        assert state["status"] == "failed"
    finally:
        server.shutdown()
        server.server_close()


def test_model_reviewer_retries_one_truncated_response_without_redrafting(
    client: TestClient, demo_project: dict,
) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    server, base_url = start_phase5_server(reviewer_truncations=1)
    try:
        configure_phase5_roles(client, base_url, reviewers=True)
        contract = derive_locked_contract(client, project_id)
        job = client.post(
            f"/api/v1/projects/{project_id}/chapter-jobs",
            json={"chapterContractId": contract["id"]},
        ).json()
        response = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/run", json={})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "human_review"

        quality = client.get(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/quality").json()
        reviewer_runs = [item for item in quality["runs"] if item["gateType"] == "model"]
        assert {item["reviewerRole"] for item in reviewer_runs} == {
            "continuity_reviewer", "story_editor", "style_reviewer",
        }
        model_runs = client.get(f"/api/v1/projects/{project_id}/model-runs?limit=50").json()
        assert sum(item["status"] == "failed" and item["errorCode"] == "content_truncated" for item in model_runs) == 1, (
            [(item["role"], item["status"], item["errorCode"]) for item in model_runs],
            server.RequestHandlerClass.post_count,
            server.RequestHandlerClass.reviewer_truncations_remaining,
        )
        assert sum(item["status"] == "succeeded" and item["role"] == "continuity_reviewer" for item in model_runs) == 1
        # One writer call plus four extraction sections and four reviewer calls
        # proves the safe draft was not regenerated after the reviewer retry.
        assert server.RequestHandlerClass.post_count == 9
        assert contract["requiredForeshadows"]
        assert server.RequestHandlerClass.observed_required_foreshadows == contract["requiredForeshadows"]
    finally:
        server.shutdown()
        server.server_close()


def test_extraction_normalizes_common_model_shape_without_promoting_narrative_boundaries(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    service = client.app.state.story_service
    project = service.get_project(project_id)
    payload = service.phase5._normalize_extraction_payload({"chapterNumber": 1, "title": "Test"}, {
        "entities": [
            {"id": "e1", "type": "character", "name": "Lin Mo", "description": "protagonist"},
            {"id": "e2", "type": "artifact", "name": "Night Lamp"},
        ],
        "facts": [
            {"subject": "Lin Mo", "predicate": "location", "object": "archive", "expectedCurrentValue": True, "stateChanging": True},
            {"description": "ambient observation", "stateChanging": False},
        ],
        "events": [{"sequence": 1, "description": "Lin Mo enters the archive."}],
        "foreshadows": [{"id": "f1", "description": "A fourth bell rings."}],
        "boundaries": [{"type": "narrative_restriction", "description": "Do not reveal the culprit."}],
    })
    assert payload["entities"][0]["canonicalName"] == "Lin Mo"
    assert payload["entities"][0]["entityTypeName"] == "person"
    assert payload["entities"][1]["entityTypeName"] == "item"
    assert payload["facts"] == [{
        "entity": "Lin Mo",
        "fieldPath": "location",
        "value": "archive",
        "confidence": 1.0,
    }]
    assert payload["events"][0]["eventOrder"] == 1
    assert payload["foreshadows"][0]["code"] == "f1"
    assert payload["boundaries"] == []
    with service.db.project(project.id, project.folder_path) as session:
        service.phase4._validate_state_payload(session, project.id, payload)


def test_model_provider_call_occurs_without_holding_project_write_lock(client: TestClient, demo_project: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = demo_project["id"]
    configure_phase5_roles(client, "http://127.0.0.1:9")
    service = client.app.state.story_service
    project = service.get_project(project_id)
    observed = {"lockOwned": True}

    async def inspect_lock(_self: object, _payload: dict) -> ModelStreamResult:
        lock = service.db._locks[project_id]
        observed["lockOwned"] = bool(getattr(lock, "_is_owned", lambda: False)())
        return ModelStreamResult(text="draft body")

    monkeypatch.setattr(phase5_module.OpenAICompatibleModelProvider, "complete_chat", inspect_lock)
    text, _run_id = service.phase5._complete_role_text(project, "chinese_writer", "lock-test", [{"role": "user", "content": "write"}], response_json=False)
    assert text == "draft body"
    assert observed["lockOwned"] is False


def test_deterministic_gate_blocks_forbidden_content_and_pace_overflow(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    server, base_url = start_phase5_server()
    try:
        configure_phase5_roles(client, base_url, reviewers=True)
        node_id = client.get(f"/api/v1/projects/{project_id}/plan").json()["milestones"][0]["id"]
        contract = client.post(f"/api/v1/projects/{project_id}/chapter-contracts/derive", json={
            "chapterNumber": 1,
            "planNodeId": node_id,
            "targetWordsMin": 5,
            "targetWordsMax": 100,
        }).json()
        updated = client.put(f"/api/v1/projects/{project_id}/chapter-contracts/{contract['id']}", json={
            "expectedRevision": contract["revision"],
            "forbiddenScope": {"forbiddenCharacters": ["Lin Mo"]},
            "allowedScope": {**contract["allowedScope"], "paceBudget": {"maxMajorEvents": 0}},
        })
        assert updated.status_code == 200, updated.text
        locked = client.post(f"/api/v1/projects/{project_id}/chapter-contracts/{contract['id']}/lock", json={"expectedRevision": updated.json()["revision"]}).json()
        job = client.post(f"/api/v1/projects/{project_id}/chapter-jobs", json={"chapterContractId": locked["id"]}).json()
        assert client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/run", json={}).status_code == 200
        codes = {item["ruleCode"] for item in client.get(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/quality").json()["findings"]}
        assert {"FORBIDDEN_CHARACTER_EARLY", "PACE_MAJOR_EVENT_OVERFLOW"}.issubset(codes)
    finally:
        server.shutdown()
        server.server_close()


def test_cancel_requested_job_settles_to_cancelled_without_becoming_failed(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    contract = derive_locked_contract(client, project_id)
    job = client.post(f"/api/v1/projects/{project_id}/chapter-jobs", json={"chapterContractId": contract["id"]}).json()
    service = client.app.state.story_service
    project = service.get_project(project_id)
    with service.db.project_write(project.id, project.folder_path) as session:
        row = session.get(ChapterJob, job["id"])
        row.status = "cancel_requested"
    with pytest.raises(StoryError) as raised:
        service.phase5._raise_if_cancel_requested(project, job["id"])
    assert raised.value.code == "CHAPTER_JOB_CANCELLED"
    state = client.get(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}").json()
    assert state["status"] == "cancelled"
    assert state["errorCode"] == "cancelled"


def test_rewrite_supersedes_prior_source_and_keeps_one_current_fact_and_commit(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    server, base_url = start_phase5_server()
    try:
        configure_phase5_roles(client, base_url, reviewers=True)
        _first_contract, first_job, first_approved = run_and_approve_job(client, project_id)
        first_commit_response = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{first_job['id']}/commit", json={"expectedJobRevision": first_approved["revision"]})
        assert first_commit_response.status_code == 200, first_commit_response.text
        first_commit = first_commit_response.json()

        _second_contract, second_job, second_approved = run_and_approve_job(client, project_id)
        second_commit_response = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{second_job['id']}/commit", json={"expectedJobRevision": second_approved["revision"]})
        assert second_commit_response.status_code == 200, second_commit_response.text
        second_commit = second_commit_response.json()

        service = client.app.state.story_service
        project = service.get_project(project_id)
        with service.db.project(project.id, project.folder_path) as session:
            old_source = session.get(SourceVersion, first_commit["sourceVersionId"])
            new_source = session.get(SourceVersion, second_commit["sourceVersionId"])
            assert old_source.status == "superseded"
            assert new_source.status == "official"
            assert new_source.version_number == old_source.version_number + 1
            current_commits = session.scalars(select(ChapterCommit).where(ChapterCommit.chapter_number == 1, ChapterCommit.is_current.is_(True))).all()
            assert [item.id for item in current_commits] == [second_commit["id"]]
            current_facts = session.scalars(select(StateFact).where(StateFact.is_current.is_(True))).all()
            assert len([item for item in current_facts if item.field_path == "location"]) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_manual_revision_creates_version_and_can_restore_previous_candidate(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    server, base_url = start_phase5_server()
    try:
        configure_phase5_roles(client, base_url, reviewers=True)
        contract = derive_locked_contract(client, project_id)
        job = client.post(f"/api/v1/projects/{project_id}/chapter-jobs", json={"chapterContractId": contract["id"]}).json()
        run = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/run", json={})
        assert run.status_code == 200, run.text
        initial_job = run.json()
        first = client.get(f"/api/v1/projects/{project_id}/chapters/1/drafts").json()[0]
        assert first["isCurrent"] is True

        manual = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/manual-revisions", json={
            "contentMarkdown": "Lin Mo entered the old house slowly. The required condition is now visible.",
            "reason": "tighten the opening",
            "parentDraftId": first["id"],
            "expectedParentRevision": first["revision"],
            "expectedJobRevision": initial_job["revision"],
        })
        assert manual.status_code == 200, manual.text
        versions = client.get(f"/api/v1/projects/{project_id}/chapters/1/drafts").json()
        current = next(item for item in versions if item["isCurrent"])
        previous = next(item for item in versions if item["id"] == first["id"])
        assert current["versionNumber"] == 2
        assert current["kind"] == "manual"
        assert previous["isCurrent"] is False

        stale = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/manual-revisions", json={
            "contentMarkdown": "stale edit",
            "parentDraftId": first["id"],
            "expectedParentRevision": previous["revision"],
            "expectedJobRevision": manual.json()["revision"],
        })
        assert stale.status_code == 409
        assert stale.json()["code"] == "CHAPTER_DRAFT_NOT_CURRENT"

        restored = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/drafts/{previous['id']}/activate", json={
            "expectedDraftRevision": previous["revision"],
            "expectedJobRevision": manual.json()["revision"],
        })
        assert restored.status_code == 200, restored.text
        versions = client.get(f"/api/v1/projects/{project_id}/chapters/1/drafts").json()
        assert next(item for item in versions if item["isCurrent"])["id"] == previous["id"]
        assert sum(1 for item in versions if item["isCurrent"]) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_chapter_commit_history_endpoint_survives_refresh(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    lock_canon(client, project_id)
    server, base_url = start_phase5_server()
    try:
        configure_phase5_roles(client, base_url, reviewers=True)
        _contract, job, approved = run_and_approve_job(client, project_id)
        committed = client.post(f"/api/v1/projects/{project_id}/chapter-jobs/{job['id']}/commit", json={"expectedJobRevision": approved["revision"]})
        assert committed.status_code == 200, committed.text
        history = client.get(f"/api/v1/projects/{project_id}/chapters/1/commits")
        assert history.status_code == 200, history.text
        assert history.json()[0]["id"] == committed.json()["id"]
        assert history.json()[0]["isCurrent"] is True
        assert client.get(f"/api/v1/projects/{project_id}/chapters/2/commits").json() == []
    finally:
        server.shutdown()
        server.server_close()
