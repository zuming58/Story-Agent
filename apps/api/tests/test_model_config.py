from __future__ import annotations

import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient


class FakeOpenAIHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/models":
            self.send_response(404)
            self.end_headers()
            return
        auth = self.headers.get("Authorization", "")
        if auth != "Bearer unit-test-secret-value":
            self.send_response(401)
            self.end_headers()
            return
        body = b'{"data":[{"id":"fake-planner"}]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


def start_fake_openai() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOpenAIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


def test_provider_secret_is_stored_outside_sqlite_and_connection_test_uses_fake_service(client: TestClient, data_dir: Path) -> None:
    server, base_url = start_fake_openai()
    try:
        response = client.post("/api/v1/model-providers", json={
            "name": "本地假 OpenAI",
            "baseUrl": base_url,
            "timeoutSeconds": 5,
            "maxRetries": 1,
            "apiKey": "unit-test-secret-value",
        })
        assert response.status_code == 201
        provider = response.json()
        assert provider["hasApiKey"] is True
        assert provider["apiKeyPreview"] == "-value"
        assert "unit-test-secret-value" not in response.text

        catalog_bytes = (data_dir / "catalog.db").read_bytes()
        assert b"unit-test-secret-value" not in catalog_bytes

        tested = client.post(f"/api/v1/model-providers/{provider['id']}/test")
        assert tested.status_code == 200
        assert tested.json()["status"] == "success"
        assert tested.json()["model"] == "fake-planner"
        assert "unit-test-secret-value" not in tested.text
    finally:
        server.shutdown()
        server.server_close()


def test_provider_base_url_requires_https_except_localhost(client: TestClient) -> None:
    response = client.post("/api/v1/model-providers", json={
        "name": "明文远端",
        "baseUrl": "http://example.com/v1",
    })
    assert response.status_code == 422
    assert response.json()["code"] == "INSECURE_MODEL_BASE_URL"


def test_models_and_role_bindings_protect_provider_delete(client: TestClient) -> None:
    provider = client.post("/api/v1/model-providers", json={
        "name": "DeepSeek 中转",
        "baseUrl": "https://api.deepseek.com",
    }).json()
    model = client.post(f"/api/v1/model-providers/{provider['id']}/models", json={
        "modelId": "deepseek-v4-pro",
        "displayName": "DeepSeek V4 Pro",
        "temperature": 0.6,
        "maxOutputTokens": 4096,
        "supportsReasoning": True,
    })
    assert model.status_code == 201
    model_id = model.json()["id"]

    bound = client.put("/api/v1/model-role-bindings/planner", json={"modelId": model_id, "dailyCostLimit": 12})
    assert bound.status_code == 200
    assert bound.json()["model"]["modelId"] == "deepseek-v4-pro"

    delete_model = client.delete(f"/api/v1/models/{model_id}")
    assert delete_model.status_code == 409
    assert delete_model.json()["code"] == "MODEL_CONFIG_IN_USE"

    delete_provider = client.delete(f"/api/v1/model-providers/{provider['id']}")
    assert delete_provider.status_code == 409
    assert delete_provider.json()["code"] == "MODEL_PROVIDER_IN_USE"

    roles = client.get("/api/v1/model-role-bindings").json()
    assert {item["role"] for item in roles} >= {"architect", "planner", "chinese_writer", "embedding"}


def test_deleting_unused_provider_clears_secret_reference(client: TestClient, data_dir: Path) -> None:
    created = client.post("/api/v1/model-providers", json={
        "name": "临时 Provider",
        "baseUrl": "https://api.example.test",
        "apiKey": "unit-test-delete-me",
    }).json()
    deleted = client.delete(f"/api/v1/model-providers/{created['id']}")
    assert deleted.status_code == 204

    with sqlite3.connect(data_dir / "catalog.db") as db:
        rows = db.execute("select api_key_ref from model_providers where id = ?", (created["id"],)).fetchall()
    assert rows == []
