from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient


class Phase5OpenAIHandler(BaseHTTPRequestHandler):
    post_count = 0

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
        if wants_json and "contentMarkdown" in joined:
            content = json.dumps({"contentMarkdown": "Lin Mo pushed open the old house door. The required condition is now visible."})
        elif wants_json and "requiredOutput" in joined:
            content = json.dumps({"findings": []})
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
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *_args: object) -> None:
        return


def start_phase5_server() -> tuple[ThreadingHTTPServer, str]:
    class Handler(Phase5OpenAIHandler):
        pass

    Handler.post_count = 0
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
