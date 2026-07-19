from __future__ import annotations

import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

from story_agent_api.secrets import MemorySecretStore, SecretStoreUnavailable


class FailingDeleteSecretStore(MemorySecretStore):
    def delete_secret(self, key: str) -> None:
        raise SecretStoreUnavailable("delete failed")


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


def test_provider_base_url_rejects_embedded_credentials_and_query(client: TestClient) -> None:
    for base_url in ("https://user:secret@example.com/v1", "https://example.com/v1?key=secret"):
        response = client.post("/api/v1/model-providers", json={
            "name": "不安全 Provider",
            "baseUrl": base_url,
        })
        assert response.status_code == 422
        assert response.json()["code"] == "INVALID_MODEL_BASE_URL"


def test_deepseek_preset_is_idempotent_and_uses_current_model_identifier(client: TestClient) -> None:
    first = client.post("/api/v1/model-providers/deepseek-preset")
    second = client.post("/api/v1/model-providers/deepseek-preset")
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]

    providers = client.get("/api/v1/model-providers").json()
    assert [item["id"] for item in providers].count(first.json()["id"]) == 1
    models = client.get(f"/api/v1/model-providers/{first.json()['id']}/models").json()
    assert [item["modelId"] for item in models] == ["deepseek-v4-pro"]
    assert models[0]["inputPricePerMillion"] == 0.435
    assert models[0]["outputPricePerMillion"] == 0.87


def test_volcengine_coding_plan_preset_is_idempotent_and_keeps_subscription_pricing_unset(client: TestClient) -> None:
    first = client.post("/api/v1/model-providers/volcengine-coding-plan-preset")
    second = client.post("/api/v1/model-providers/volcengine-coding-plan-preset")
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert first.json()["name"] == "火山引擎 Coding Plan"
    assert first.json()["baseUrl"] == "https://ark.cn-beijing.volces.com/api/coding/v3"
    assert first.json()["hasApiKey"] is False

    models = client.get(f"/api/v1/model-providers/{first.json()['id']}/models").json()
    by_model_id = {item["modelId"]: item for item in models}
    assert set(by_model_id) == {"Kimi-K2.6", "DeepSeek-V4-Pro"}
    assert by_model_id["Kimi-K2.6"]["inputPricePerMillion"] is None
    assert by_model_id["DeepSeek-V4-Pro"]["outputPricePerMillion"] is None


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


def test_bulk_model_role_binding_is_atomic_and_preserves_cost_limits(client: TestClient) -> None:
    provider = client.post("/api/v1/model-providers", json={
        "name": "双模型测试 Provider",
        "baseUrl": "https://api.example.test",
    }).json()
    writer = client.post(f"/api/v1/model-providers/{provider['id']}/models", json={
        "modelId": "fiction-writer",
        "displayName": "正文模型",
    }).json()
    reviewer = client.post(f"/api/v1/model-providers/{provider['id']}/models", json={
        "modelId": "structure-reviewer",
        "displayName": "审校模型",
    }).json()

    assert client.put("/api/v1/model-role-bindings/planner", json={"modelId": reviewer["id"], "dailyCostLimit": 12}).status_code == 200
    applied = client.put("/api/v1/model-role-bindings/bulk", json={
        "modelIds": {
            "chinese_writer": writer["id"],
            "reviser": writer["id"],
            "planner": reviewer["id"],
            "continuity_reviewer": reviewer["id"],
        },
    })
    assert applied.status_code == 200
    by_role = {item["role"]: item for item in client.get("/api/v1/model-role-bindings").json()}
    assert by_role["chinese_writer"]["modelId"] == writer["id"]
    assert by_role["reviser"]["modelId"] == writer["id"]
    assert by_role["planner"]["modelId"] == reviewer["id"]
    assert by_role["planner"]["dailyCostLimit"] == 12

    rejected = client.put("/api/v1/model-role-bindings/bulk", json={
        "modelIds": {"chinese_writer": writer["id"], "story_editor": "missing-model"},
    })
    assert rejected.status_code == 404
    assert rejected.json()["code"] == "MODEL_CONFIG_NOT_FOUND"
    after_reject = {item["role"]: item for item in client.get("/api/v1/model-role-bindings").json()}
    assert after_reject["story_editor"]["modelId"] is None


def test_model_price_database_guards_reject_negative_values(client: TestClient, data_dir: Path) -> None:
    provider = client.post("/api/v1/model-providers", json={
        "name": "Priced Provider",
        "baseUrl": "https://api.example.test",
    }).json()
    model = client.post(f"/api/v1/model-providers/{provider['id']}/models", json={
        "modelId": "priced-model",
        "displayName": "Priced Model",
        "inputPricePerMillion": 1.0,
        "outputPricePerMillion": 2.0,
    }).json()
    with sqlite3.connect(data_dir / "catalog.db") as db:
        try:
            db.execute("update model_configs set input_price_per_million = -1 where id = ?", (model["id"],))
        except sqlite3.IntegrityError as exc:
            assert "non-negative" in str(exc)
        else:
            raise AssertionError("negative model pricing bypassed the database guard")


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


def test_provider_delete_keeps_catalog_row_if_secret_delete_fails(client: TestClient, data_dir: Path) -> None:
    service = client.app.state.story_service
    service.secret_store = FailingDeleteSecretStore()
    created = client.post("/api/v1/model-providers", json={
        "name": "删除失败 Provider",
        "baseUrl": "https://api.example.test",
        "apiKey": "unit-test-stays-cleanup",
    }).json()

    deleted = client.delete(f"/api/v1/model-providers/{created['id']}")
    assert deleted.status_code == 503
    assert deleted.json()["code"] == "CREDENTIAL_STORE_UNAVAILABLE"

    with sqlite3.connect(data_dir / "catalog.db") as db:
        rows = db.execute("select id, api_key_ref from model_providers where id = ?", (created["id"],)).fetchall()
    assert rows == [(created["id"], f"model-provider:{created['id']}")]
