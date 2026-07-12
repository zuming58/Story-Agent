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
        }) if wants_json else "Lin Mo pushed open the old house door.\n\nA cold clue waited under the lamp."
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


def configure_phase5_roles(client: TestClient, base_url: str) -> None:
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
    for role in ("chinese_writer", "fact_extractor"):
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
        runs = client.get(f"/api/v1/projects/{project_id}/model-runs").json()
        assert {item["role"] for item in runs[:2]} == {"chinese_writer", "fact_extractor"}
    finally:
        server.shutdown()
        server.server_close()
