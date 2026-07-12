from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient


class StreamingOpenAIHandler(BaseHTTPRequestHandler):
    mode = "success"

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/chat/completions":
            self.send_response(404)
            self.end_headers()
            return
        auth = self.headers.get("Authorization", "")
        if auth != "Bearer unit-stream-secret" or self.mode == "auth":
            self.send_response(401)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        chunks = [
            {"model": "fake-stream-model", "choices": [{"delta": {"content": "第一段"}}]},
            {"model": "fake-stream-model", "choices": [{"delta": {"content": "第二段"}}]},
            {"model": "fake-stream-model", "choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}},
        ]
        for chunk in chunks:
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/models":
            body = b'{"data":[{"id":"fake-stream-model"}]}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *_args: object) -> None:
        return


def start_server(mode: str = "success") -> tuple[ThreadingHTTPServer, str]:
    class Handler(StreamingOpenAIHandler):
        pass

    Handler.mode = mode
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


def configure_planner(client: TestClient, base_url: str) -> tuple[str, str]:
    provider = client.post("/api/v1/model-providers", json={
        "name": "流式假模型",
        "baseUrl": base_url,
        "timeoutSeconds": 5,
        "maxRetries": 1,
        "apiKey": "unit-stream-secret",
    }).json()
    model = client.post(f"/api/v1/model-providers/{provider['id']}/models", json={
        "modelId": "fake-stream-model",
        "displayName": "Fake Stream",
    }).json()
    bound = client.put("/api/v1/model-role-bindings/planner", json={"modelId": model["id"]})
    assert bound.status_code == 200
    return provider["id"], model["id"]


def first_session(client: TestClient, project_id: str) -> str:
    sessions = client.get(f"/api/v1/projects/{project_id}/agent/sessions").json()
    return sessions[0]["id"]


def test_streaming_agent_records_model_run_and_assistant_message(client: TestClient, demo_project: dict) -> None:
    server, base_url = start_server()
    try:
        configure_planner(client, base_url)
        session_id = first_session(client, demo_project["id"])
        with client.stream("POST", f"/api/v1/agent/sessions/{session_id}/messages/stream", json={
            "projectId": demo_project["id"],
            "content": "请检查当前节奏。",
            "selectedNodeId": "milestone-paper-man",
        }) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())
        assert "event: run_started" in body
        assert "event: text_delta" in body
        assert "第一段" in body and "第二段" in body
        assert "event: completed" in body

        sessions = client.get(f"/api/v1/projects/{demo_project['id']}/agent/sessions").json()
        assert sessions[0]["messages"][-1]["role"] == "assistant"
        assert sessions[0]["messages"][-1]["content"] == "第一段第二段"
        runs = client.get(f"/api/v1/projects/{demo_project['id']}/model-runs").json()
        assert runs[0]["status"] == "succeeded"
        assert runs[0]["modelId"] == "fake-stream-model"
        assert runs[0]["totalTokens"] == 18
    finally:
        server.shutdown()
        server.server_close()


def test_streaming_agent_fails_without_planner_binding(client: TestClient, demo_project: dict) -> None:
    session_id = first_session(client, demo_project["id"])
    with client.stream("POST", f"/api/v1/agent/sessions/{session_id}/messages/stream", json={
        "projectId": demo_project["id"],
        "content": "请使用真实模型。",
    }) as response:
        body = "".join(response.iter_text())
    assert "MODEL_ROLE_NOT_CONFIGURED" in body


def test_streaming_auth_failure_is_a_failed_run(client: TestClient, demo_project: dict) -> None:
    server, base_url = start_server(mode="auth")
    try:
        configure_planner(client, base_url)
        session_id = first_session(client, demo_project["id"])
        with client.stream("POST", f"/api/v1/agent/sessions/{session_id}/messages/stream", json={
            "projectId": demo_project["id"],
            "content": "请检查鉴权。",
        }) as response:
            body = "".join(response.iter_text())
        assert "auth_failed" in body
        runs = client.get(f"/api/v1/projects/{demo_project['id']}/model-runs").json()
        assert runs[0]["status"] == "failed"
        assert runs[0]["errorCode"] == "auth_failed"
    finally:
        server.shutdown()
        server.server_close()


def test_cancel_model_run_marks_existing_running_record(client: TestClient, demo_project: dict) -> None:
    server, base_url = start_server()
    try:
        configure_planner(client, base_url)
        session_id = first_session(client, demo_project["id"])
        service = client.app.state.story_service
        project = service.get_project(demo_project["id"])
        run_id = "manual-running-run"
        with service.db.project_write(project.id, project.folder_path) as db:
            from story_agent_api.models import ModelRun
            from story_agent_api.models import utc_now

            db.add(ModelRun(
                id=run_id,
                session_id=session_id,
                role="planner",
                provider_name="流式假模型",
                model_id="fake-stream-model",
                status="running",
                request_id="req-test",
                started_at=utc_now(),
            ))
        cancelled = client.post(f"/api/v1/projects/{demo_project['id']}/model-runs/{run_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancel_requested"
    finally:
        server.shutdown()
        server.server_close()
