from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import story_agent_api.phase4 as phase4_module
from story_agent_api.config import Settings
from story_agent_api.main import create_app
from story_agent_api.model_provider import ModelStreamResult
from story_agent_api.secrets import MemorySecretStore


def _entity_type(client: TestClient, project_id: str, name: str = "person") -> dict:
    canon = client.get(f"/api/v1/projects/{project_id}/canon")
    assert canon.status_code == 200, canon.text
    return next(item for item in canon.json()["entityTypes"] if item["name"] == name)


def _candidate_payload(
    type_id: str,
    source_id: str,
    version: int,
    *,
    value: str = "旧宅",
    expected: object = ...,
    event_summary: str = "林默进入旧宅",
) -> dict:
    fact: dict = {"entity": "林默", "fieldPath": "location", "value": value}
    if expected is not ...:
        fact["expectedCurrentValue"] = expected
    return {
        "sourceId": source_id,
        "versionNumber": version,
        "sourceKind": "chapter",
        "summary": event_summary,
        "entities": [{
            "entityTypeId": type_id,
            "canonicalName": "林默",
            "aliases": ["小林"],
            "attributes": {"name": "林默"},
        }],
        "facts": [fact],
        "events": [{"eventOrder": version, "summary": event_summary, "participants": ["林默"]}],
        "foreshadows": [{
            "code": f"F-{version}",
            "label": f"第{version}条伏笔",
            "description": event_summary,
            "status": "pending",
            "earliestChapter": version,
            "targetChapter": version + 2,
            "latestChapter": version + 4,
        }],
        "boundaries": [{"entity": "林默", "knowledge": {"knows": event_summary}}],
    }


def _create_and_commit(client: TestClient, project_id: str, payload: dict) -> dict:
    created = client.post(f"/api/v1/projects/{project_id}/state/candidates", json=payload)
    assert created.status_code == 200, created.text
    candidate = created.json()
    committed = client.post(
        f"/api/v1/state/candidates/{candidate['id']}/commit",
        json={"projectId": project_id, "expectedRevision": candidate["revision"]},
    )
    assert committed.status_code == 200, committed.text
    return committed.json()


def test_canon_entity_type_uses_schema_json_alias(client: TestClient, demo_project: dict) -> None:
    entity_type = _entity_type(client, demo_project["id"])
    assert "schemaJson" in entity_type
    assert "schema_data" not in entity_type


def test_locked_canon_requires_change_request_and_entity_patch_applies(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    entity_type = _entity_type(client, project_id)
    draft = client.put(f"/api/v1/projects/{project_id}/canon/draft", json={
        "entities": [{
            "entityTypeId": entity_type["id"],
            "canonicalName": "林默",
            "aliasesJson": ["小林"],
            "attributesJson": {"name": "林默"},
            "status": "locked",
        }],
    })
    assert draft.status_code == 200, draft.text
    entity = draft.json()["entities"][0]
    assert entity["status"] == "draft", "客户端不能绕过锁定流程"

    root = next(item for item in draft.json()["documents"] if item["id"] == "story-core")
    locked = client.post(f"/api/v1/projects/{project_id}/canon/lock", json={"expectedRevision": root["revision"]})
    assert locked.status_code == 200, locked.text
    rejected_direct_edit = client.put(f"/api/v1/projects/{project_id}/canon/draft", json={"documents": [{"id": "story-core", "contentMarkdown": "越权修改"}]})
    assert rejected_direct_edit.status_code == 409
    assert rejected_direct_edit.json()["code"] == "CANON_LOCKED"

    change = client.post(f"/api/v1/projects/{project_id}/canon/change-requests", json={
        "projectId": project_id,
        "targetKind": "entity",
        "targetId": entity["id"],
        "reason": "移除不再使用的别名",
        "beforeJson": {"aliasesJson": ["伪造的客户端快照"]},
        "afterJson": {"aliasesJson": []},
    })
    assert change.status_code == 200, change.text
    assert change.json()["beforeJson"]["aliases"] == ["小林"], "before 快照必须由服务端生成"
    applied = client.post(f"/api/v1/canon/change-requests/{change.json()['id']}/apply", json={
        "projectId": project_id,
        "expectedRevision": change.json()["revision"],
    })
    assert applied.status_code == 200, applied.text
    canon = client.get(f"/api/v1/projects/{project_id}/canon").json()
    updated = next(item for item in canon["entities"] if item["id"] == entity["id"])
    assert updated["aliases"] == []
    assert updated["status"] == "locked"


def test_state_commit_is_atomic_and_conflicts_do_not_overwrite(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    type_id = _entity_type(client, project_id)["id"]
    _create_and_commit(client, project_id, _candidate_payload(type_id, "chapter-1", 1))

    second_payload = _candidate_payload(type_id, "chapter-2", 1, value="码头", event_summary="林默抵达码头")
    second = client.post(f"/api/v1/projects/{project_id}/state/candidates", json=second_payload).json()
    conflict = client.post(f"/api/v1/state/candidates/{second['id']}/commit", json={
        "projectId": project_id,
        "expectedRevision": second["revision"],
    })
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "STATE_FACT_CONFLICT"

    entity = client.get(f"/api/v1/projects/{project_id}/state/entities").json()[0]
    detail = client.get(f"/api/v1/projects/{project_id}/state/entities/{entity['id']}").json()
    assert detail["facts"][0]["valueJson"] == "旧宅"
    timeline = client.get(f"/api/v1/projects/{project_id}/state/timeline").json()
    assert all("码头" not in str(item) for item in timeline), "失败事务不得留下事件或增量"
    snapshots = client.get(f"/api/v1/projects/{project_id}/state/snapshots").json()
    assert len(snapshots) == 1
    audit = client.get(f"/api/v1/projects/{project_id}/audit-events").json()
    assert any(item["eventType"] == "state.conflict_detected" and item["entityId"] == second["id"] for item in audit)


def test_explicit_state_transition_and_supersede_replay_indexes(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    type_id = _entity_type(client, project_id)["id"]
    first = _create_and_commit(client, project_id, _candidate_payload(type_id, "chapter-1", 1))
    second = _create_and_commit(
        client,
        project_id,
        _candidate_payload(type_id, "chapter-2", 1, value="码头", expected="旧宅", event_summary="林默抵达码头"),
    )
    assert first["status"] == second["status"] == "official"
    before = client.post(f"/api/v1/projects/{project_id}/retrieval/search", json={"query": "码头", "limit": 10})
    assert before.status_code == 200 and before.json()

    superseded = client.post(f"/api/v1/source-versions/{second['id']}/supersede", json={
        "projectId": project_id,
        "expectedRevision": second["revision"],
    })
    assert superseded.status_code == 200, superseded.text
    assert superseded.json()["status"] == "superseded"
    entity = client.get(f"/api/v1/projects/{project_id}/state/entities").json()[0]
    detail = client.get(f"/api/v1/projects/{project_id}/state/entities/{entity['id']}").json()
    assert detail["facts"][0]["valueJson"] == "旧宅", "作废后必须回放上一个正式事实"
    assert all("码头" not in str(item) for item in client.get(f"/api/v1/projects/{project_id}/state/timeline").json())
    assert all("码头" not in str(item) for item in client.get(f"/api/v1/projects/{project_id}/state/foreshadows").json())
    assert client.post(f"/api/v1/projects/{project_id}/retrieval/search", json={"query": "码头", "limit": 10}).json() == []


def test_invalid_state_candidate_rolls_back_and_duplicate_source_version_is_rejected(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    type_id = _entity_type(client, project_id)["id"]
    payload = _candidate_payload(type_id, "chapter-invalid", 1)
    payload["foreshadows"][0]["earliestChapter"] = 10
    payload["foreshadows"][0]["targetChapter"] = 2
    created = client.post(f"/api/v1/projects/{project_id}/state/candidates", json=payload)
    assert created.status_code == 200
    duplicate = client.post(f"/api/v1/projects/{project_id}/state/candidates", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "SOURCE_VERSION_EXISTS"
    failed = client.post(f"/api/v1/state/candidates/{created.json()['id']}/commit", json={
        "projectId": project_id,
        "expectedRevision": 1,
    })
    assert failed.status_code == 422
    assert failed.json()["code"] == "STATE_PAYLOAD_INVALID"
    assert client.get(f"/api/v1/projects/{project_id}/state/entities").json() == []
    assert client.get(f"/api/v1/projects/{project_id}/state/snapshots").json() == []


def test_context_compiler_preserves_canon_contract_state_and_trace(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    root = client.get(f"/api/v1/projects/{project_id}/canon").json()["documents"][0]
    assert client.post(f"/api/v1/projects/{project_id}/canon/lock", json={"expectedRevision": root["revision"]}).status_code == 200
    type_id = _entity_type(client, project_id)["id"]
    _create_and_commit(client, project_id, _candidate_payload(type_id, "chapter-1", 1))
    node_id = client.get(f"/api/v1/projects/{project_id}/plan").json()["milestones"][0]["id"]

    compiled = client.post(f"/api/v1/projects/{project_id}/context/compile", json={
        "query": "林默",
        "role": "writer",
        "selectedNodeId": node_id,
        "tokenBudget": 256,
    })
    assert compiled.status_code == 200, compiled.text
    package = compiled.json()
    included_kinds = {item["kind"] for item in package["items"] if item["included"]}
    assert {"canon_document", "task_contract", "state_fact", "knowledge_boundary"}.issubset(included_kinds)
    traced = client.get(f"/api/v1/projects/{project_id}/context/traces/{package['traceId']}")
    assert traced.status_code == 200
    assert traced.json()["checksum"] == package["checksum"]
    assert traced.json()["items"] == package["payload"]["items"]


class _UnavailableVectorBackend:
    name = "unavailable-test-vector"
    available = False

    def upsert(self, project_id: str, entries: list[dict]) -> None:
        raise AssertionError("unavailable vector backend must not be called")

    def delete_source_version(self, project_id: str, source_version_id: str) -> None:
        raise AssertionError("unavailable vector backend must not be called")

    def rebuild(self, project_id: str, entries: list[dict]) -> None:
        raise AssertionError("unavailable vector backend must not be called")

    def search(self, rows: list[dict], query: str, limit: int) -> list[dict]:
        raise AssertionError("unavailable vector backend must not be called")


def test_fts_remains_available_when_vector_backend_is_down(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    root = client.get(f"/api/v1/projects/{project_id}/canon").json()["documents"][0]
    assert client.post(f"/api/v1/projects/{project_id}/canon/lock", json={"expectedRevision": root["revision"]}).status_code == 200
    service = client.app.state.story_service
    service.phase4.vector_backend = _UnavailableVectorBackend()
    rebuilt = client.post(f"/api/v1/projects/{project_id}/retrieval/rebuild")
    assert rebuilt.status_code == 200
    assert rebuilt.json()["vectorAvailable"] is False
    response = client.post(f"/api/v1/projects/{project_id}/retrieval/search", json={"query": demo_project["title"], "limit": 10})
    assert response.status_code == 200
    assert response.json(), "精确/FTS 检索必须在向量服务不可用时继续工作"


def test_markdown_mirror_failure_is_diagnosed_without_rolling_back_database(
    client: TestClient,
    demo_project: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = demo_project["id"]

    def fail_write(_path: Path, _content: str) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr(phase4_module, "_atomic_write_text", fail_write)
    response = client.put(f"/api/v1/projects/{project_id}/canon/draft", json={
        "documents": [{"id": "story-core", "title": "镜像故障测试", "contentMarkdown": "# 数据库仍应成功"}],
    })
    assert response.status_code == 200, response.text
    assert response.json()["documents"][0]["title"] == "镜像故障测试"
    audit = client.get(f"/api/v1/projects/{project_id}/audit-events").json()
    assert any(item["eventType"] == "canon.mirror_failed" for item in audit)


def test_unsafe_canon_schema_is_rejected(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    response = client.put(f"/api/v1/projects/{project_id}/canon/draft", json={
        "entityTypes": [{
            "name": "unsafe",
            "displayName": "不安全类型",
            "schemaJson": {"type": "string", "pattern": "(a+)+$"},
        }],
    })
    assert response.status_code == 422
    assert response.json()["code"] == "CANON_SCHEMA_INVALID"
    names = {item["name"] for item in client.get(f"/api/v1/projects/{project_id}/canon").json()["entityTypes"]}
    assert "unsafe" not in names


def test_canon_relation_references_are_validated_transactionally(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    response = client.put(f"/api/v1/projects/{project_id}/canon/draft", json={
        "relations": [{
            "subjectEntityId": "missing-subject",
            "predicate": "knows",
            "objectValueJson": "秘密",
        }],
        "rules": [{"ruleCode": "SHOULD_ROLL_BACK", "statement": "不得残留"}],
    })
    assert response.status_code == 422
    assert response.json()["code"] == "CANON_SCHEMA_INVALID"
    canon = client.get(f"/api/v1/projects/{project_id}/canon").json()
    assert all(item["ruleCode"] != "SHOULD_ROLL_BACK" for item in canon["rules"])


def test_rejected_canon_change_does_not_modify_locked_target(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    root = client.get(f"/api/v1/projects/{project_id}/canon").json()["documents"][0]
    assert client.post(f"/api/v1/projects/{project_id}/canon/lock", json={"expectedRevision": root["revision"]}).status_code == 200
    change = client.post(f"/api/v1/projects/{project_id}/canon/change-requests", json={
        "projectId": project_id,
        "targetKind": "document",
        "targetId": "story-core",
        "reason": "尝试改标题",
        "afterJson": {"title": "不应生效"},
    }).json()
    rejected = client.post(f"/api/v1/canon/change-requests/{change['id']}/reject", json={
        "projectId": project_id,
        "expectedRevision": change["revision"],
    })
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    current = client.get(f"/api/v1/projects/{project_id}/canon").json()["documents"][0]
    assert current["title"] == root["title"]


def test_path_and_body_project_ids_must_match(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    response = client.post(f"/api/v1/projects/{project_id}/canon/change-requests", json={
        "projectId": "another-project",
        "targetKind": "document",
        "targetId": "story-core",
        "reason": "跨作品请求",
        "afterJson": {"title": "无效"},
    })
    assert response.status_code == 422
    assert response.json()["code"] == "PROJECT_ID_MISMATCH"


def test_source_revision_and_status_guards(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    type_id = _entity_type(client, project_id)["id"]
    created = client.post(
        f"/api/v1/projects/{project_id}/state/candidates",
        json=_candidate_payload(type_id, "chapter-guard", 1),
    ).json()
    stale = client.post(f"/api/v1/state/candidates/{created['id']}/commit", json={
        "projectId": project_id,
        "expectedRevision": created["revision"] + 1,
    })
    assert stale.status_code == 409
    assert stale.json()["code"] == "STATE_REVISION_CONFLICT"
    premature = client.post(f"/api/v1/source-versions/{created['id']}/supersede", json={
        "projectId": project_id,
        "expectedRevision": created["revision"],
    })
    assert premature.status_code == 409
    assert premature.json()["code"] == "SOURCE_VERSION_NOT_OFFICIAL"


def test_unknown_state_references_are_rejected_without_partial_materialization(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    payload = {
        "sourceId": "chapter-unknown",
        "versionNumber": 1,
        "sourceKind": "chapter",
        "facts": [{"entity": "不存在的人", "fieldPath": "location", "value": "旧宅"}],
    }
    candidate = client.post(f"/api/v1/projects/{project_id}/state/candidates", json=payload).json()
    committed = client.post(f"/api/v1/state/candidates/{candidate['id']}/commit", json={
        "projectId": project_id,
        "expectedRevision": candidate["revision"],
    })
    assert committed.status_code == 422
    assert committed.json()["code"] == "STATE_PAYLOAD_INVALID"
    assert client.get(f"/api/v1/projects/{project_id}/state/entities").json() == []


def test_context_compiler_rejects_unknown_selected_node(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    response = client.post(f"/api/v1/projects/{project_id}/context/compile", json={
        "role": "writer",
        "selectedNodeId": "missing-node",
        "tokenBudget": 512,
    })
    assert response.status_code == 404
    assert response.json()["code"] == "PLAN_NODE_NOT_FOUND"


def test_retrieval_hits_include_source_and_checksum_evidence(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    type_id = _entity_type(client, project_id)["id"]
    official = _create_and_commit(client, project_id, _candidate_payload(type_id, "chapter-evidence", 1))
    hits = client.post(f"/api/v1/projects/{project_id}/retrieval/search", json={"query": "林默", "limit": 10}).json()
    assert hits
    entity_hit = next(item for item in hits if item["kind"] == "entity")
    assert entity_hit["sourceVersionId"] == official["id"]
    assert entity_hit["sourceStatus"] == "official"
    assert len(entity_hit["checksum"]) == 64


def test_canon_analysis_invalid_json_retries_once_without_writing_or_echoing_raw_output(
    client: TestClient,
    demo_project: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = client.post("/api/v1/model-providers", json={
        "name": "Architect Test",
        "baseUrl": "https://architect.example.test",
        "apiKey": "architect-secret",
    }).json()
    model = client.post(f"/api/v1/model-providers/{provider['id']}/models", json={
        "modelId": "architect-json-test",
        "displayName": "Architect JSON Test",
    }).json()
    assert client.put("/api/v1/model-role-bindings/architect", json={"modelId": model["id"]}).status_code == 200
    calls = 0

    async def invalid_json(_self: object, _payload: dict) -> ModelStreamResult:
        nonlocal calls
        calls += 1
        return ModelStreamResult(text="RAW_MODEL_SECRET:not-json")

    monkeypatch.setattr(phase4_module.OpenAICompatibleModelProvider, "complete_chat", invalid_json)
    before = client.get(f"/api/v1/projects/{demo_project['id']}/canon").json()
    response = client.post(f"/api/v1/projects/{demo_project['id']}/canon/analyze", json={
        "projectId": demo_project["id"],
        "sourceText": "请分析这个故事设定",
    })
    assert response.status_code == 422
    assert response.json()["code"] == "CANON_ANALYSIS_INVALID"
    assert calls == 2
    assert "RAW_MODEL_SECRET" not in response.text
    assert client.get(f"/api/v1/projects/{demo_project['id']}/canon").json() == before


def test_custom_canon_schema_rejects_wrong_attribute_type_and_extra_fields(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    response = client.put(f"/api/v1/projects/{project_id}/canon/draft", json={
        "entityTypes": [{
            "name": "cultivation_level",
            "displayName": "修炼等级",
            "schemaJson": {
                "type": "object",
                "properties": {"level": {"type": "integer"}},
                "required": ["level"],
                "additionalProperties": False,
            },
        }],
    })
    assert response.status_code == 200
    custom = next(item for item in response.json()["entityTypes"] if item["name"] == "cultivation_level")
    invalid = client.put(f"/api/v1/projects/{project_id}/canon/draft", json={
        "entities": [{
            "entityTypeId": custom["id"],
            "canonicalName": "林默境界",
            "attributesJson": {"level": "一", "unexpected": True},
        }],
    })
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "CANON_SCHEMA_INVALID"
    assert all(item["canonicalName"] != "林默境界" for item in client.get(f"/api/v1/projects/{project_id}/canon").json()["entities"])


def test_rebuild_is_deterministic_and_projects_are_isolated(client: TestClient, demo_project: dict) -> None:
    first_id = demo_project["id"]
    first_type = _entity_type(client, first_id)["id"]
    _create_and_commit(client, first_id, _candidate_payload(first_type, "first-only", 1, event_summary="第一部独有证据"))
    first_checksum = client.post(f"/api/v1/projects/{first_id}/retrieval/rebuild").json()["checksum"]
    assert client.post(f"/api/v1/projects/{first_id}/retrieval/rebuild").json()["checksum"] == first_checksum

    second = client.post("/api/v1/projects", json={"title": "第二部", "mode": "long-form", "totalChapters": 80}).json()
    second_type = _entity_type(client, second["id"])["id"]
    sentinel = "SECOND_PROJECT_SENTINEL_9281"
    _create_and_commit(client, second["id"], _candidate_payload(second_type, "second-only", 1, event_summary=sentinel))
    assert client.post(f"/api/v1/projects/{first_id}/retrieval/search", json={"query": sentinel, "limit": 10}).json() == []
    assert client.post(f"/api/v1/projects/{second['id']}/retrieval/search", json={"query": sentinel, "limit": 10}).json()


def test_backup_restore_includes_phase4_state_and_locked_canon(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    root = client.get(f"/api/v1/projects/{project_id}/canon").json()["documents"][0]
    assert client.post(f"/api/v1/projects/{project_id}/canon/lock", json={"expectedRevision": root["revision"]}).status_code == 200
    type_id = _entity_type(client, project_id)["id"]
    _create_and_commit(client, project_id, _candidate_payload(type_id, "backup-source", 1))
    backup = client.post(f"/api/v1/projects/{project_id}/backups").json()
    archive = Path(backup["archivePath"])
    restored = client.post(
        "/api/v1/projects/restore",
        files={"backup": (archive.name, archive.read_bytes(), "application/zip")},
    )
    assert restored.status_code == 201, restored.text
    restored_id = restored.json()["id"]
    assert client.get(f"/api/v1/projects/{restored_id}/canon").json()["locked"] is True
    restored_entities = client.get(f"/api/v1/projects/{restored_id}/state/entities").json()
    assert restored_entities and restored_entities[0]["canonicalName"] == "林默"
    assert client.get(f"/api/v1/projects/{restored_id}/state/snapshots").json()


def test_phase4_state_survives_service_restart(client: TestClient, demo_project: dict, data_dir: Path) -> None:
    project_id = demo_project["id"]
    root = client.get(f"/api/v1/projects/{project_id}/canon").json()["documents"][0]
    assert client.post(f"/api/v1/projects/{project_id}/canon/lock", json={"expectedRevision": root["revision"]}).status_code == 200
    type_id = _entity_type(client, project_id)["id"]
    _create_and_commit(client, project_id, _candidate_payload(type_id, "restart-source", 1))

    restarted_app = create_app(Settings(data_dir=data_dir, seed_demo=True), secret_store=MemorySecretStore())
    with TestClient(restarted_app) as restarted:
        assert restarted.get(f"/api/v1/projects/{project_id}/canon").json()["locked"] is True
        assert restarted.get(f"/api/v1/projects/{project_id}/state/entities").json()
        assert restarted.get(f"/api/v1/projects/{project_id}/state/snapshots").json()
        hits = restarted.post(f"/api/v1/projects/{project_id}/retrieval/search", json={"query": "林默", "limit": 10})
        assert hits.status_code == 200 and hits.json()
