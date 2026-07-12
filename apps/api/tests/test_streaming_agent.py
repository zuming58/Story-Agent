from __future__ import annotations

import json
import pytest
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient
from story_agent_api.schemas import AgentMessageCreate


class StreamingOpenAIHandler(BaseHTTPRequestHandler):
    mode = "success"
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
        auth = self.headers.get("Authorization", "")
        if auth != "Bearer unit-stream-secret" or self.mode == "auth":
            self.send_response(401)
            self.end_headers()
            return
        if not request.get("stream"):
            self._send_json_completion(request)
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

    def _send_json_completion(self, request: dict) -> None:
        mode = type(self).mode
        if mode == "invalid-json-repair" and type(self).post_count == 2:
            content = "{bad json"
        elif mode == "forbidden-field":
            content = json.dumps({
                "targetId": "milestone-paper-man",
                "expectedRevision": 1,
                "reason": "尝试改写锁定字段",
                "operations": [{"field": "title", "after": "越界标题"}],
                "impacts": [],
            }, ensure_ascii=False)
        elif mode == "revision-conflict":
            content = json.dumps({
                "targetId": "milestone-paper-man",
                "expectedRevision": 999,
                "reason": "过期版本提案",
                "operations": [{"field": "targetChapter", "after": 23}],
                "impacts": [],
            }, ensure_ascii=False)
        elif mode == "noop":
            content = json.dumps({
                "targetId": "milestone-paper-man",
                "expectedRevision": 1,
                "reason": "逻辑边界通过，不建议改动。",
                "operations": [],
                "impacts": [],
            }, ensure_ascii=False)
        else:
            content = json.dumps({
                "targetId": "milestone-paper-man",
                "expectedRevision": 1,
                "reason": "把纸人正面对抗推迟到铺垫完成之后。",
                "operations": [
                    {"field": "targetChapter", "after": 24},
                    {"field": "rangeMin", "after": 22},
                    {"field": "rangeMax", "after": 26},
                    {"field": "prerequisites", "after": ["已触发事件：收到旧宅来信（章 8）", "node:milestone-letter"]},
                ],
                "impacts": [{"kind": "dependency", "label": "前置依赖将补全"}],
            }, ensure_ascii=False)
        body = json.dumps({
            "model": "fake-stream-model",
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 19, "completion_tokens": 13, "total_tokens": 32},
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
    Handler.post_count = 0
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
        # A provider failure may race with the cancel request. The persisted
        # cancel request must still win and return the session to idle.
        service._complete_model_run_failure(project.id, project.folder_path, session_id, run_id, "failed", "network_error", 0)
        runs = client.get(f"/api/v1/projects/{demo_project['id']}/model-runs").json()
        assert next(run for run in runs if run["id"] == run_id)["status"] == "cancelled"
        sessions = client.get(f"/api/v1/projects/{demo_project['id']}/agent/sessions").json()
        assert next(item for item in sessions if item["id"] == session_id)["status"] == "idle"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.anyio
async def test_streaming_generator_close_marks_run_cancelled(client: TestClient, demo_project: dict) -> None:
    server, base_url = start_server()
    try:
        configure_planner(client, base_url)
        session_id = first_session(client, demo_project["id"])
        service = client.app.state.story_service
        generator = service.stream_agent_message(session_id, AgentMessageCreate(
            projectId=demo_project["id"],
            content="请检查当前节奏。",
            selectedNodeId="milestone-paper-man",
            action="chat",
        ), "req-disconnect")
        started = await generator.__anext__()
        assert started["event"] == "run_started"
        run_id = started["runId"]
        await generator.aclose()

        runs = client.get(f"/api/v1/projects/{demo_project['id']}/model-runs").json()
        run = next(item for item in runs if item["id"] == run_id)
        assert run["status"] == "cancelled"
        assert run["errorCode"] == "client_disconnected"
    finally:
        server.shutdown()
        server.server_close()


def test_structured_replan_generates_pending_json_proposal(client: TestClient, demo_project: dict) -> None:
    server, base_url = start_server()
    try:
        configure_planner(client, base_url)
        session_id = first_session(client, demo_project["id"])
        with client.stream("POST", f"/api/v1/agent/sessions/{session_id}/messages/stream", json={
            "projectId": demo_project["id"],
            "content": "请重排当前里程碑。",
            "selectedNodeId": "milestone-paper-man",
            "action": "replan",
        }) as response:
            body = "".join(response.iter_text())
        assert "event: proposal_started" in body
        assert "event: proposal_completed" in body
        proposals = client.get(f"/api/v1/projects/{demo_project['id']}/change-proposals", params={"status": "pending"}).json()
        proposal = proposals[0]
        assert proposal["targetId"] == "milestone-paper-man"
        assert any(operation["field"] == "prerequisites" for operation in proposal["operations"])
        runs = client.get(f"/api/v1/projects/{demo_project['id']}/model-runs").json()
        proposal_run = next(run for run in runs if run["role"] == "planner_proposal")
        assert proposal_run["status"] == "succeeded"
        assert proposal_run["diagnostic"]["proposalId"] == proposal["id"]
    finally:
        server.shutdown()
        server.server_close()


def test_structured_json_repair_retry_before_proposal_success(client: TestClient, demo_project: dict) -> None:
    server, base_url = start_server(mode="invalid-json-repair")
    try:
        configure_planner(client, base_url)
        session_id = first_session(client, demo_project["id"])
        with client.stream("POST", f"/api/v1/agent/sessions/{session_id}/messages/stream", json={
            "projectId": demo_project["id"],
            "content": "请补全依赖。",
            "selectedNodeId": "milestone-paper-man",
            "action": "complete_dependencies",
        }) as response:
            body = "".join(response.iter_text())
        assert "event: proposal_completed" in body
        assert '"attempts": 2' in body or '"attempts":2' in body
    finally:
        server.shutdown()
        server.server_close()


def test_logic_check_noop_is_successful_diagnostic_not_failed_proposal(client: TestClient, demo_project: dict) -> None:
    server, base_url = start_server(mode="noop")
    try:
        configure_planner(client, base_url)
        session_id = first_session(client, demo_project["id"])
        with client.stream("POST", f"/api/v1/agent/sessions/{session_id}/messages/stream", json={
            "projectId": demo_project["id"],
            "content": "请检查逻辑，如果无需修改就说明通过。",
            "selectedNodeId": "milestone-paper-man",
            "action": "logic_check",
        }) as response:
            body = "".join(response.iter_text())
        assert "event: proposal_skipped" in body
        assert "proposal_failed" not in body
        runs = client.get(f"/api/v1/projects/{demo_project['id']}/model-runs").json()
        proposal_run = next(run for run in runs if run["role"] == "planner_proposal")
        assert proposal_run["status"] == "succeeded"
        assert proposal_run["diagnostic"]["reason"] == "PROPOSAL_NO_OPERATIONS"
        audits = client.get(f"/api/v1/projects/{demo_project['id']}/audit-events").json()
        assert audits[0]["eventType"] == "proposal.noop"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.anyio
async def test_disconnect_during_proposal_keeps_natural_reply_and_cancels_proposal_run(client: TestClient, demo_project: dict) -> None:
    server, base_url = start_server()
    try:
        configure_planner(client, base_url)
        session_id = first_session(client, demo_project["id"])
        service = client.app.state.story_service
        generator = service.stream_agent_message(session_id, AgentMessageCreate(
            projectId=demo_project["id"],
            content="请重排当前里程碑。",
            selectedNodeId="milestone-paper-man",
            action="replan",
        ), "req-proposal-disconnect")

        while True:
            event = await generator.__anext__()
            if event["event"] == "proposal_started":
                break
        await generator.aclose()

        runs = client.get(f"/api/v1/projects/{demo_project['id']}/model-runs").json()
        natural_run = next(run for run in runs if run["role"] == "planner")
        proposal_run = next(run for run in runs if run["role"] == "planner_proposal")
        assert natural_run["status"] == "succeeded"
        assert proposal_run["status"] == "cancelled"
        assert proposal_run["errorCode"] == "client_disconnected"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.anyio
async def test_manual_stop_cancels_structured_proposal_before_model_request(client: TestClient, demo_project: dict) -> None:
    server, base_url = start_server()
    try:
        configure_planner(client, base_url)
        session_id = first_session(client, demo_project["id"])
        service = client.app.state.story_service
        pending_before = client.get(f"/api/v1/projects/{demo_project['id']}/change-proposals", params={"status": "pending"}).json()
        generator = service.stream_agent_message(session_id, AgentMessageCreate(
            projectId=demo_project["id"],
            content="请重排当前里程碑。",
            selectedNodeId="milestone-paper-man",
            action="replan",
        ), "req-proposal-stop")

        proposal_started = None
        while proposal_started is None:
            event = await generator.__anext__()
            if event["event"] == "proposal_started":
                proposal_started = event
        cancelled = service.cancel_model_run(demo_project["id"], proposal_started["runId"])
        assert cancelled["status"] == "cancel_requested"
        event = await generator.__anext__()
        assert event["event"] == "cancelled"
        await generator.aclose()

        runs = client.get(f"/api/v1/projects/{demo_project['id']}/model-runs").json()
        proposal_run = next(run for run in runs if run["id"] == proposal_started["runId"])
        assert proposal_run["status"] == "cancelled"
        pending_after = client.get(f"/api/v1/projects/{demo_project['id']}/change-proposals", params={"status": "pending"}).json()
        assert pending_after == pending_before
    finally:
        server.shutdown()
        server.server_close()


def test_replan_noop_is_reported_as_failed_proposal(client: TestClient, demo_project: dict) -> None:
    server, base_url = start_server(mode="noop")
    try:
        configure_planner(client, base_url)
        session_id = first_session(client, demo_project["id"])
        with client.stream("POST", f"/api/v1/agent/sessions/{session_id}/messages/stream", json={
            "projectId": demo_project["id"],
            "content": "请重排当前里程碑。",
            "selectedNodeId": "milestone-paper-man",
            "action": "replan",
        }) as response:
            body = "".join(response.iter_text())
        assert "event: proposal_failed" in body
        assert "PROPOSAL_NO_OPERATIONS" in body
        assert "event: proposal_skipped" not in body
    finally:
        server.shutdown()
        server.server_close()


def test_structured_proposal_forbidden_field_records_failure_without_inserting(client: TestClient, demo_project: dict) -> None:
    server, base_url = start_server(mode="forbidden-field")
    try:
        configure_planner(client, base_url)
        session_id = first_session(client, demo_project["id"])
        before = client.get(f"/api/v1/projects/{demo_project['id']}/change-proposals", params={"status": "pending"}).json()
        with client.stream("POST", f"/api/v1/agent/sessions/{session_id}/messages/stream", json={
            "projectId": demo_project["id"],
            "content": "请检查逻辑。",
            "selectedNodeId": "milestone-paper-man",
            "action": "logic_check",
        }) as response:
            body = "".join(response.iter_text())
        assert "PROPOSAL_FIELD_NOT_ALLOWED" in body
        after = client.get(f"/api/v1/projects/{demo_project['id']}/change-proposals", params={"status": "pending"}).json()
        assert len(after) == len(before)
        audits = client.get(f"/api/v1/projects/{demo_project['id']}/audit-events").json()
        assert audits[0]["eventType"] == "proposal.generation_failed"
    finally:
        server.shutdown()
        server.server_close()


def test_structured_proposal_revision_conflict_does_not_change_plan(client: TestClient, demo_project: dict) -> None:
    server, base_url = start_server(mode="revision-conflict")
    try:
        configure_planner(client, base_url)
        session_id = first_session(client, demo_project["id"])
        before = client.get(f"/api/v1/projects/{demo_project['id']}/plan").json()
        with client.stream("POST", f"/api/v1/agent/sessions/{session_id}/messages/stream", json={
            "projectId": demo_project["id"],
            "content": "请重排。",
            "selectedNodeId": "milestone-paper-man",
            "action": "replan",
        }) as response:
            body = "".join(response.iter_text())
        assert "PROPOSAL_REVISION_CONFLICT" in body
        assert client.get(f"/api/v1/projects/{demo_project['id']}/plan").json() == before
    finally:
        server.shutdown()
        server.server_close()
