from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

import httpx
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session, selectinload

from .model_provider import ModelProviderError, OpenAICompatibleModelProvider
from .models import (
    AuditEvent,
    CanonChangeRequest,
    CanonDocument,
    CanonEntity,
    CanonEntityType,
    CanonRelation,
    CanonRule,
    ContextTrace,
    Foreshadow,
    KnowledgeBoundary,
    ProjectMeta,
    RetrievalIndexState,
    SourceVersion,
    StateDelta,
    StateFact,
    StateSnapshot,
    StoryEvent,
    StoryEntity,
)
from .schemas import (
    CanonAnalyzeRequest,
    CanonChangeRequestCreate,
    CanonChangeRequestDecision,
    CanonChangeRequestOut,
    CanonDocumentOut,
    CanonDraftUpdate,
    CanonEntityOut,
    CanonEntityTypeOut,
    CanonLockRequest,
    CanonRelationOut,
    CanonRuleOut,
    ContextCompileRequest,
    ContextPackageOut,
    ContextTraceItemOut,
    ForeshadowOut,
    KnowledgeBoundaryOut,
    RetrievalHit,
    RetrievalQuery,
    RetrievalStatus,
    SourceVersionOut,
    SourceVersionSupersede,
    StateCandidateCommit,
    StateCandidateCreate,
    StateDeltaOut,
    StateFactOut,
    StateSnapshotOut,
    StoryEntityOut,
    StoryEventOut,
)


def _story_error(status: int, code: str, message: str, details: dict[str, Any] | None = None):
    from .services import StoryError

    return StoryError(status, code, message, details)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except ValueError:
        return default


def _stable_digest(value: Any) -> str:
    return hashlib.sha256(_dumps(value).encode("utf-8")).hexdigest()


def _token_estimate(text_value: str) -> int:
    return 0 if not text_value else max(1, (len(text_value) + 3) // 4)


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(path)


def _json_schema_subset_valid(schema: Any, value: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, dict):
            return False
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return False
        required = schema.get("required", [])
        if isinstance(required, list) and any(name not in value for name in required):
            return False
        if schema.get("additionalProperties", True) is False:
            allowed = set(properties)
            if any(key not in allowed for key in value):
                return False
        for key, prop_schema in properties.items():
            if key in value and not _json_schema_subset_valid(prop_schema, value[key]):
                return False
        return True
    if schema_type == "array":
        if not isinstance(value, list):
            return False
        items = schema.get("items")
        return True if items is None else all(_json_schema_subset_valid(items, item) for item in value)
    if schema_type == "string":
        return isinstance(value, str) and (not schema.get("enum") or value in schema["enum"])
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "null":
        return value is None
    if schema_type is None:
        return True
    return False


def _canon_schema_is_safe(schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    allowed_keys = {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "description",
        "title",
        "default",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
    }
    if any(key not in allowed_keys for key in schema):
        return False
    if schema.get("type") not in {"object", "array", "string", "integer", "number", "boolean", "null", None}:
        return False
    if "pattern" in schema or "format" in schema:
        return False
    items = schema.get("items")
    if items is not None and not _canon_schema_is_safe(items):
        return False
    for key in ("properties", "definitions", "$defs"):
        nested = schema.get(key)
        if isinstance(nested, dict) and any(not _canon_schema_is_safe(item) for item in nested.values()):
            return False
    return True


class Phase4Service:
    DEFAULT_ENTITY_TYPES = [
        ("person", "人物", {"type": "object", "properties": {"name": {"type": "string"}, "aliases": {"type": "array", "items": {"type": "string"}}}, "additionalProperties": True}),
        ("location", "地点", {"type": "object", "properties": {"name": {"type": "string"}, "region": {"type": "string"}}, "additionalProperties": True}),
        ("organization", "组织", {"type": "object", "properties": {"name": {"type": "string"}}, "additionalProperties": True}),
        ("item", "物品", {"type": "object", "properties": {"name": {"type": "string"}, "rarity": {"type": "string"}}, "additionalProperties": True}),
        ("ability", "能力", {"type": "object", "properties": {"name": {"type": "string"}, "cost": {"type": "string"}}, "additionalProperties": True}),
        ("event", "事件", {"type": "object", "properties": {"name": {"type": "string"}}, "additionalProperties": True}),
        ("intel", "情报", {"type": "object", "properties": {"name": {"type": "string"}}, "additionalProperties": True}),
        ("foreshadow", "伏笔", {"type": "object", "properties": {"name": {"type": "string"}}, "additionalProperties": True}),
        ("time_point", "时间点", {"type": "object", "properties": {"name": {"type": "string"}}, "additionalProperties": True}),
    ]

    def __init__(self, service: Any):
        self.service = service
        self._vector_cache: dict[str, dict[str, dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # Project defaults
    # ------------------------------------------------------------------
    def ensure_existing_projects(self) -> None:
        for project in self.service.list_projects():
            self.ensure_project_defaults(project.id, project.folder_path, project.title)

    def ensure_project_defaults(self, project_id: str, folder_path: str, project_title: str) -> None:
        with self.service.db.project_write(project_id, folder_path) as session:
            now = datetime.now(timezone.utc)
            if session.get(CanonDocument, "story-core") is None:
                session.add(CanonDocument(
                    id="story-core",
                    title=f"{project_title} Story Core",
                    kind="story-core",
                    content_markdown=f"# {project_title} Story Core\n\n> Status: draft canon foundation.\n",
                    status="draft",
                    created_at=now,
                    updated_at=now,
                ))
            existing_types = set(session.scalars(select(CanonEntityType.name)).all())
            for name, display_name, schema_json in self.DEFAULT_ENTITY_TYPES:
                if name not in existing_types:
                    session.add(CanonEntityType(
                        id=str(uuid4()),
                        name=name,
                        display_name=display_name,
                        schema_json=_dumps(schema_json),
                        is_system=True,
                        status="locked",
                        revision=1,
                        locked_at=now,
                        created_at=now,
                        updated_at=now,
                    ))
            if session.get(RetrievalIndexState, project_id) is None:
                session.add(RetrievalIndexState(
                    project_id=project_id,
                    last_rebuilt_at=None,
                    indexed_count=0,
                    vector_backend="sqlite-local",
                    vector_available=True,
                    checksum="",
                    updated_at=now,
                ))

    # ------------------------------------------------------------------
    # Canon
    # ------------------------------------------------------------------
    def get_canon(self, project_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            return {
                "projectId": project.id,
                "locked": bool(session.scalar(select(CanonDocument).where(CanonDocument.status == "locked"))),
                "documents": [self._document_out(item).model_dump(mode="json", by_alias=True) for item in session.scalars(select(CanonDocument).order_by(CanonDocument.created_at.asc())).all()],
                "entityTypes": [self._entity_type_out(item).model_dump(mode="json", by_alias=True) for item in session.scalars(select(CanonEntityType).order_by(CanonEntityType.created_at.asc())).all()],
                "entities": [self._canon_entity_out(item).model_dump(mode="json", by_alias=True) for item in session.scalars(select(CanonEntity).order_by(CanonEntity.created_at.asc())).all()],
                "relations": [self._relation_out(item).model_dump(mode="json", by_alias=True) for item in session.scalars(select(CanonRelation).order_by(CanonRelation.created_at.asc())).all()],
                "rules": [self._rule_out(item).model_dump(mode="json", by_alias=True) for item in session.scalars(select(CanonRule).order_by(CanonRule.created_at.asc())).all()],
                "changeRequests": [self._change_request_out(item).model_dump(mode="json", by_alias=True) for item in session.scalars(select(CanonChangeRequest).order_by(CanonChangeRequest.created_at.desc())).all()],
            }

    def update_canon_draft(self, project_id: str, payload: CanonDraftUpdate) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            if session.scalar(select(CanonDocument).where(CanonDocument.status == "locked")):
                raise _story_error(409, "CANON_LOCKED", "Canon 已锁定，只能通过变更申请修改。")
            now = datetime.now(timezone.utc)
            for item in payload.documents:
                self._upsert_document(session, item, now)
            for item in payload.entity_types:
                self._upsert_entity_type(session, item, now)
            for item in payload.entities:
                self._upsert_entity(session, item, now)
            for item in payload.relations:
                self._upsert_relation(session, item, now)
            for item in payload.rules:
                self._upsert_rule(session, item, now)
        self._mirror_canon_markdown_for_project(project.id, project.folder_path)
        return self.get_canon(project_id)

    def analyze_canon(self, project_id: str, payload: CanonAnalyzeRequest, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        resolved = self.service._resolve_role_model("architect")
        if not resolved:
            raise _story_error(409, "MODEL_ROLE_NOT_CONFIGURED", "Architect 角色尚未绑定模型。")
        provider = resolved["provider"]
        model = resolved["model"]
        if not provider.api_key_ref:
            raise _story_error(409, "MODEL_API_KEY_MISSING", "Architect 角色尚未配置 API Key。")
        try:
            api_key = self.service.secret_store.get_secret(provider.api_key_ref)
        except Exception as exc:  # pragma: no cover - defensive
            raise _story_error(503, "CREDENTIAL_STORE_UNAVAILABLE", "Credential Manager 不可用，无法读取 API Key。") from exc
        if not api_key:
            raise _story_error(409, "MODEL_API_KEY_MISSING", "Credential Manager 中未找到 Architect API Key。")

        provider_client = OpenAICompatibleModelProvider(provider.base_url, api_key, provider.timeout_seconds, provider.max_retries)
        prompt_messages = [
            {
                "role": "system",
                "content": "你是 Story Agent 的 Canon 分析器。只输出 JSON object，字段包含 documents、entityTypes、entities、relations、rules。",
            },
            {
                "role": "user",
                "content": json.dumps({
                    "projectId": project.id,
                    "projectTitle": project.title,
                    "sourceText": payload.source_text,
                    "title": payload.title,
                }, ensure_ascii=False),
            },
        ]
        response = None
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                result = awaitable_response = None
                async def _run() -> Any:
                    return await provider_client.complete_chat({
                        "model": model.model_id,
                        "messages": prompt_messages if attempt == 0 else prompt_messages + [{
                            "role": "system",
                            "content": "上一次输出无效。请只返回合法 JSON object，不要 Markdown，不要解释。",
                        }],
                        "temperature": min(float(model.temperature), 0.2),
                        "max_tokens": model.max_output_tokens,
                        "response_format": {"type": "json_object"},
                    })
                # bridge async inside sync method
                import asyncio

                result = asyncio.run(_run())
                response = result.text
                data = json.loads(response or "")
                if not isinstance(data, dict):
                    raise ValueError("not object")
                self.update_canon_draft(project_id, CanonDraftUpdate(
                    documents=data.get("documents", []) if isinstance(data.get("documents"), list) else [],
                    entity_types=data.get("entityTypes", []) if isinstance(data.get("entityTypes"), list) else [],
                    entities=data.get("entities", []) if isinstance(data.get("entities"), list) else [],
                    relations=data.get("relations", []) if isinstance(data.get("relations"), list) else [],
                    rules=data.get("rules", []) if isinstance(data.get("rules"), list) else [],
                ))
                with self.service.db.project_write(project.id, project.folder_path) as session:
                    session.add(self.service._audit("canon.analysis_completed", "canon_document", "story-core", {
                        "requestId": request_id,
                        "attempt": attempt + 1,
                        "reversible": False,
                    }, request_id))
                return self.get_canon(project_id)
            except (json.JSONDecodeError, ModelProviderError, ValueError) as exc:
                last_error = exc
                continue
            except Exception as exc:
                from .services import StoryError

                if isinstance(exc, StoryError):
                    raise
                raise _story_error(422, "CANON_ANALYSIS_INVALID", f"Canon 分析失败: {exc}") from exc
        raise _story_error(422, "CANON_ANALYSIS_INVALID", "Canon 分析器未能输出有效 JSON。", {"raw": response or "", "error": str(last_error) if last_error else ""})

    def lock_canon(self, project_id: str, payload: CanonLockRequest, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            root = session.get(CanonDocument, "story-core")
            if not root:
                raise _story_error(404, "CANON_NOT_FOUND", "Canon 不存在。")
            if root.status == "locked":
                raise _story_error(409, "CANON_LOCKED", "Canon 已锁定。")
            if root.revision != payload.expected_revision:
                raise _story_error(409, "REVISION_CONFLICT", "Canon 版本已变化。", {"currentRevision": root.revision})
            now = datetime.now(timezone.utc)
            before = self.get_canon(project_id)
            for model in (CanonDocument, CanonEntityType, CanonEntity, CanonRelation, CanonRule):
                for item in session.scalars(select(model)).all():
                    if hasattr(item, "status"):
                        item.status = "locked"
                    if hasattr(item, "locked_at"):
                        item.locked_at = now
                    if hasattr(item, "revision"):
                        item.revision = int(getattr(item, "revision", 1)) + 1
                    if hasattr(item, "updated_at"):
                        item.updated_at = now
            session.add(self.service._audit("canon.locked", "canon_document", root.id, {"before": before, "reversible": False}, request_id))
            self._rebuild_retrieval_index(session, project.id, now)
        self._mirror_canon_markdown_for_project(project.id, project.folder_path)
        return self.get_canon(project_id)

    def create_canon_change_request(self, project_id: str, payload: CanonChangeRequestCreate, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            item = CanonChangeRequest(
                id=str(uuid4()),
                project_id=project_id,
                target_kind=payload.target_kind,
                target_id=payload.target_id,
                reason=payload.reason,
                impact_summary=payload.impact_summary,
                before_json=_dumps(payload.before_json) if payload.before_json is not None else None,
                after_json=_dumps(payload.after_json) if payload.after_json is not None else None,
                status="pending",
                revision=1,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(item)
            session.add(self.service._audit("canon.change_request.created", payload.target_kind, payload.target_id, {"requestId": request_id}, request_id))
            session.flush()
            return self._change_request_out(item).model_dump(mode="json", by_alias=True)

    def apply_canon_change_request(self, change_request_id: str, payload: CanonChangeRequestDecision, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(payload.project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            item = session.get(CanonChangeRequest, change_request_id)
            if not item:
                raise _story_error(404, "CANON_CHANGE_REQUEST_NOT_FOUND", "Canon 变更申请不存在。")
            if item.revision != payload.expected_revision:
                raise _story_error(409, "REVISION_CONFLICT", "Canon 变更申请版本冲突。", {"currentRevision": item.revision})
            if item.status != "pending":
                raise _story_error(409, "CANON_CHANGE_REQUEST_ALREADY_RESOLVED", "Canon 变更申请已处理。")
            target = self._resolve_canon_target(session, item.target_kind, item.target_id)
            if target is None:
                raise _story_error(404, "CANON_TARGET_NOT_FOUND", "Canon 目标不存在。")
            self._apply_canon_target_patch(target, _loads(item.after_json, {}))
            item.status = "accepted"
            item.revision += 1
            item.updated_at = datetime.now(timezone.utc)
            target.updated_at = datetime.now(timezone.utc)
            if hasattr(target, "revision"):
                target.revision = int(getattr(target, "revision", 1)) + 1
            if hasattr(target, "locked_at"):
                target.locked_at = datetime.now(timezone.utc)
            session.add(self.service._audit("canon.change_request.applied", item.target_kind, item.target_id, {"changeRequestId": item.id}, request_id))
            self._rebuild_retrieval_index(session, project.id, datetime.now(timezone.utc))
        self._mirror_canon_markdown_for_project(project.id, project.folder_path)
        return self._change_request_out(item).model_dump(mode="json", by_alias=True)

    def reject_canon_change_request(self, change_request_id: str, payload: CanonChangeRequestDecision, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(payload.project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            item = session.get(CanonChangeRequest, change_request_id)
            if not item:
                raise _story_error(404, "CANON_CHANGE_REQUEST_NOT_FOUND", "Canon 变更申请不存在。")
            if item.revision != payload.expected_revision:
                raise _story_error(409, "REVISION_CONFLICT", "Canon 变更申请版本冲突。")
            if item.status != "pending":
                raise _story_error(409, "CANON_CHANGE_REQUEST_ALREADY_RESOLVED", "Canon 变更申请已处理。")
            item.status = "rejected"
            item.revision += 1
            item.updated_at = datetime.now(timezone.utc)
            session.add(self.service._audit("canon.change_request.rejected", item.target_kind, item.target_id, {"changeRequestId": item.id}, request_id))
            return self._change_request_out(item).model_dump(mode="json", by_alias=True)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    def create_state_candidate(self, project_id: str, payload: StateCandidateCreate, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            item = SourceVersion(
                id=str(uuid4()),
                project_id=project_id,
                source_id=payload.source_id,
                version_number=payload.version_number,
                source_kind=payload.source_kind,
                status="candidate",
                checksum=_stable_digest(payload.model_dump()),
                summary=payload.summary,
                payload_json=_dumps(payload.model_dump()),
                revision=1,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(item)
            session.add(self.service._audit("state.candidate.created", "source_version", item.id, {"requestId": request_id}, request_id))
            session.flush()
            return self._source_version_out(item).model_dump(mode="json", by_alias=True)

    def commit_state_candidate(self, candidate_id: str, payload: StateCandidateCommit, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(payload.project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            candidate = session.get(SourceVersion, candidate_id)
            if not candidate:
                raise _story_error(404, "SOURCE_VERSION_NOT_FOUND", "来源版本不存在。")
            if candidate.revision != payload.expected_revision:
                raise _story_error(409, "STATE_REVISION_CONFLICT", "来源版本已变化。", {"currentRevision": candidate.revision})
            if candidate.status not in {"candidate", "official"}:
                raise _story_error(409, "SOURCE_VERSION_NOT_OFFICIAL", "来源版本不处于可提交状态。")
            if candidate.status == "official":
                return self._source_version_out(candidate).model_dump(mode="json", by_alias=True)
            data = _loads(candidate.payload_json, {})
            now = datetime.now(timezone.utc)
            self._materialize_state_payload(session, project.id, data, candidate.id, now)
            candidate.status = "official"
            candidate.revision += 1
            candidate.updated_at = now
            snapshot = self._create_state_snapshot(session, project.id, candidate.id, data, now)
            self._rebuild_retrieval_index(session, project.id, now)
            session.add(self.service._audit("state.candidate.committed", "source_version", candidate.id, {"snapshotId": snapshot.id, "requestId": request_id}, request_id))
            return self._source_version_out(candidate).model_dump(mode="json", by_alias=True)

    def supersede_source_version(self, source_version_id: str, payload: SourceVersionSupersede, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(payload.project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            source_version = session.get(SourceVersion, source_version_id)
            if not source_version:
                raise _story_error(404, "SOURCE_VERSION_NOT_FOUND", "来源版本不存在。")
            if source_version.revision != payload.expected_revision:
                raise _story_error(409, "STATE_REVISION_CONFLICT", "来源版本已变化。")
            now = datetime.now(timezone.utc)
            source_version.status = "superseded"
            source_version.revision += 1
            source_version.updated_at = now
            for model in (StateFact, StateDelta, StoryEvent, Foreshadow, KnowledgeBoundary, StoryEntity):
                for row in session.scalars(select(model).where(getattr(model, "source_version_id") == source_version_id)).all():
                    if hasattr(row, "status"):
                        row.status = "superseded"
                    if hasattr(row, "is_current"):
                        row.is_current = False
                    if hasattr(row, "valid_to") and getattr(row, "valid_to") is None:
                        row.valid_to = now
                    if hasattr(row, "updated_at"):
                        row.updated_at = now
            session.add(self.service._audit("source_version.superseded", "source_version", source_version_id, {"requestId": request_id}, request_id))
            self._rebuild_retrieval_index(session, project.id, now)
            return self._source_version_out(source_version).model_dump(mode="json", by_alias=True)

    def list_state_entities(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            return [self._story_entity_out(item, session).model_dump(mode="json", by_alias=True) for item in session.scalars(select(StoryEntity).where(StoryEntity.project_id == project_id, StoryEntity.status == "active").order_by(StoryEntity.created_at.asc())).all()]

    def get_state_entity(self, project_id: str, entity_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            item = session.scalar(select(StoryEntity).where(StoryEntity.project_id == project_id, StoryEntity.id == entity_id))
            if not item:
                raise _story_error(404, "STATE_ENTITY_NOT_FOUND", "实体不存在。")
            out = self._story_entity_out(item, session).model_dump(mode="json", by_alias=True)
            out["facts"] = [self._state_fact_out(row).model_dump(mode="json", by_alias=True) for row in session.scalars(select(StateFact).where(StateFact.project_id == project_id, StateFact.entity_id == entity_id, StateFact.is_current.is_(True))).all()]
            return out

    def list_foreshadows(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            return [self._foreshadow_out(item).model_dump(mode="json", by_alias=True) for item in session.scalars(select(Foreshadow).where(Foreshadow.project_id == project_id).order_by(Foreshadow.created_at.asc())).all()]

    def list_timeline(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            events = session.scalars(select(StoryEvent).where(StoryEvent.project_id == project_id).order_by(StoryEvent.event_order.asc(), StoryEvent.occurred_at.asc())).all()
            deltas = session.scalars(select(StateDelta).where(StateDelta.project_id == project_id).order_by(StateDelta.created_at.asc())).all()
            timeline = [
                {"kind": "event", "payload": self._story_event_out(item).model_dump(mode="json", by_alias=True), "createdAt": item.created_at}
                for item in events
            ]
            timeline.extend([
                {"kind": "delta", "payload": self._state_delta_out(item).model_dump(mode="json", by_alias=True), "createdAt": item.created_at}
                for item in deltas
            ])
            timeline.sort(key=lambda item: item["createdAt"])
            return timeline

    def list_snapshots(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            return [self._state_snapshot_out(item).model_dump(mode="json", by_alias=True) for item in session.scalars(select(StateSnapshot).where(StateSnapshot.project_id == project_id).order_by(StateSnapshot.snapshot_number.asc())).all()]

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def search_retrieval(self, project_id: str, payload: RetrievalQuery) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            exact = self._exact_retrieval_hits(session, project.id, payload.query, payload.limit)
            fts = self._fts_retrieval_hits(session, project.id, payload.query, payload.limit)
            vector = self._vector_retrieval_hits(session, project.id, payload.query, payload.limit)
            merged: dict[str, dict[str, Any]] = {}
            for hit in exact + fts + vector:
                merged.setdefault(hit["id"], hit)
            hits = list(merged.values())[: payload.limit]
            return hits

    def rebuild_retrieval(self, project_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            now = datetime.now(timezone.utc)
            self._rebuild_retrieval_index(session, project.id, now)
            state = session.get(RetrievalIndexState, project.id)
            assert state
            return self._retrieval_status_out(project.id, state).model_dump(mode="json", by_alias=True)

    def retrieval_status(self, project_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            state = session.get(RetrievalIndexState, project.id)
            if not state:
                raise _story_error(404, "RETRIEVAL_INDEX_UNAVAILABLE", "检索索引状态不存在。")
            return self._retrieval_status_out(project.id, state).model_dump(mode="json", by_alias=True)

    # ------------------------------------------------------------------
    # Context
    # ------------------------------------------------------------------
    def compile_context(self, project_id: str, payload: ContextCompileRequest, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            trace_id = str(uuid4())
            items: list[dict[str, Any]] = []
            budget = payload.token_budget

            def add_item(kind: str, title: str, content: str, priority: int, reason: str, source_version_id: str | None = None, included: bool = True, checksum: str = "") -> None:
                token_est = _token_estimate(content)
                nonlocal budget
                include = included and (priority <= 2 or budget >= token_est)
                if include:
                    budget -= token_est
                items.append({
                    "kind": kind,
                    "title": title,
                    "sourceVersionId": source_version_id,
                    "priority": priority,
                    "tokenEstimate": token_est,
                    "reason": reason,
                    "included": include,
                    "content": content,
                    "checksum": checksum or _stable_digest({"kind": kind, "title": title, "content": content}),
                })

            for doc in session.scalars(select(CanonDocument).where(CanonDocument.project_id == project_id, CanonDocument.status == "locked").order_by(CanonDocument.created_at.asc())).all():
                add_item("canon_document", doc.title, doc.content_markdown, 0, "locked canon")
            for entity in session.scalars(select(StoryEntity).where(StoryEntity.project_id == project_id, StoryEntity.status == "active").order_by(StoryEntity.created_at.asc())).all():
                facts = session.scalars(select(StateFact).where(StateFact.project_id == project_id, StateFact.entity_id == entity.id, StateFact.is_current.is_(True))).all()
                fact_text = "; ".join(f"{fact.field_path}={_loads(fact.value_json, None)}" for fact in facts)
                add_item("state_fact", entity.canonical_name, fact_text or _dumps(_loads(entity.attributes_json, {})), 1, "current state", entity.source_version_id)
            for foreshadow in session.scalars(select(Foreshadow).where(Foreshadow.project_id == project_id, Foreshadow.status != "resolved").order_by(Foreshadow.created_at.asc())).all():
                add_item("foreshadow", foreshadow.label, foreshadow.description, 2, "unresolved foreshadow", foreshadow.source_version_id)
            for event in session.scalars(select(StoryEvent).where(StoryEvent.project_id == project_id).order_by(StoryEvent.event_order.desc(), StoryEvent.occurred_at.desc()).limit(20)).all():
                add_item("event", event.summary[:60] or event.location or event.id, event.summary, 3, "official event", event.source_version_id)
            recent_messages = session.scalars(select(ProjectMeta).where(ProjectMeta.id == project.id)).all()
            if recent_messages:
                meta = recent_messages[0]
                add_item("recent_context", meta.title, f"mode={meta.mode}; chapter={meta.current_chapter}/{meta.total_chapters}", 4, "recent project context")
            retrieval_hits = self.search_retrieval(project_id, RetrievalQuery(query=payload.query or payload.role, limit=8))
            for hit in retrieval_hits:
                add_item("retrieval_hit", hit["title"], hit["content"], 5, "retrieval evidence", hit.get("sourceVersionId"), hit.get("sourceStatus") == "official", hit.get("checksum", ""))

            included = [item for item in items if item["included"]]
            payload_json = {
                "projectId": project.id,
                "role": payload.role,
                "selectedNodeId": payload.selected_node_id,
                "query": payload.query,
                "items": included,
                "budget": payload.token_budget,
            }
            trace = ContextTrace(
                id=trace_id,
                project_id=project.id,
                role=payload.role,
                query=payload.query,
                selected_node_id=payload.selected_node_id,
                token_budget=payload.token_budget,
                package_json=_dumps(payload_json),
                checksum=_stable_digest(payload_json),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(trace)
            return {
                "traceId": trace_id,
                "projectId": project.id,
                "role": payload.role,
                "selectedNodeId": payload.selected_node_id,
                "tokenBudget": payload.token_budget,
                "items": [self._context_item_out(item).model_dump(mode="json", by_alias=True) for item in items],
                "payload": payload_json,
                "checksum": trace.checksum,
            }

    def get_context_trace(self, project_id: str, trace_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            trace = session.get(ContextTrace, trace_id)
            if not trace:
                raise _story_error(404, "CONTEXT_TRACE_NOT_FOUND", "上下文追踪不存在。")
            package = _loads(trace.package_json, {})
            package["traceId"] = trace.id
            package["checksum"] = trace.checksum
            package["createdAt"] = trace.created_at
            return package

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _ensure_story_core_document(self, session: Session, project_title: str) -> CanonDocument:
        doc = session.get(CanonDocument, "story-core")
        if doc:
            return doc
        doc = CanonDocument(
            id="story-core",
            title=f"{project_title} Story Core",
            kind="story-core",
            content_markdown=f"# {project_title} Story Core\n",
            status="draft",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(doc)
        return doc

    def _upsert_document(self, session: Session, item: dict[str, Any], now: datetime) -> None:
        doc_id = str(item.get("id") or "story-core")
        doc = session.get(CanonDocument, doc_id)
        if doc and doc.status == "locked":
            raise _story_error(409, "CANON_LOCKED", "Canon 已锁定。")
        if not doc:
            doc = CanonDocument(id=doc_id, created_at=now, updated_at=now)
            session.add(doc)
        doc.title = str(item.get("title") or doc.title or "Canon")
        doc.kind = str(item.get("kind") or "story-core")
        doc.content_markdown = str(item.get("contentMarkdown") or item.get("content_markdown") or "")
        doc.status = str(item.get("status") or doc.status or "draft")
        doc.updated_at = now

    def _upsert_entity_type(self, session: Session, item: dict[str, Any], now: datetime) -> None:
        name = str(item.get("name") or "").strip()
        if not name:
            raise _story_error(422, "CANON_SCHEMA_INVALID", "实体类型名称不能为空。")
        schema_json = item.get("schemaJson") or item.get("schema_json") or {}
        if not _canon_schema_is_safe(schema_json):
            raise _story_error(422, "CANON_SCHEMA_INVALID", "实体类型 Schema 不安全。")
        row = session.scalar(select(CanonEntityType).where(CanonEntityType.name == name))
        if row and row.status == "locked":
            raise _story_error(409, "CANON_LOCKED", "Canon 已锁定。")
        if not row:
            row = CanonEntityType(id=str(uuid4()), name=name, created_at=now, updated_at=now)
            session.add(row)
        row.display_name = str(item.get("displayName") or item.get("display_name") or name)
        row.schema_json = _dumps(schema_json)
        row.is_system = bool(item.get("isSystem", False))
        row.status = str(item.get("status") or row.status or "draft")
        row.source_document_id = item.get("sourceDocumentId") or item.get("source_document_id")
        row.updated_at = now

    def _upsert_entity(self, session: Session, item: dict[str, Any], now: datetime) -> None:
        canonical_name = str(item.get("canonicalName") or item.get("canonical_name") or "").strip()
        if not canonical_name:
            raise _story_error(422, "CANON_SCHEMA_INVALID", "实体名称不能为空。")
        entity_type_id = str(item.get("entityTypeId") or item.get("entity_type_id") or "").strip()
        entity_type = session.get(CanonEntityType, entity_type_id) if entity_type_id else None
        if entity_type is None:
            raise _story_error(422, "CANON_SCHEMA_INVALID", "实体类型不存在。")
        attributes = item.get("attributesJson") or item.get("attributes_json") or {}
        schema = _loads(entity_type.schema_json, {})
        if not _json_schema_subset_valid(schema, attributes):
            raise _story_error(422, "CANON_SCHEMA_INVALID", "实体属性不符合 Schema。")
        row = session.scalar(select(CanonEntity).where(CanonEntity.canonical_name == canonical_name))
        if row and row.status == "locked":
            raise _story_error(409, "CANON_LOCKED", "Canon 已锁定。")
        if not row:
            row = CanonEntity(id=str(uuid4()), entity_type_id=entity_type.id, canonical_name=canonical_name, created_at=now, updated_at=now)
            session.add(row)
        row.aliases_json = _dumps([alias for alias in (item.get("aliasesJson") or item.get("aliases_json") or []) if isinstance(alias, str)])
        row.attributes_json = _dumps(attributes)
        row.status = str(item.get("status") or row.status or "draft")
        row.revision = int(item.get("revision") or row.revision or 1)
        row.source_document_id = item.get("sourceDocumentId") or item.get("source_document_id")
        row.updated_at = now

    def _upsert_relation(self, session: Session, item: dict[str, Any], now: datetime) -> None:
        relation_id = str(item.get("id") or uuid4())
        row = session.get(CanonRelation, relation_id)
        if row and row.status == "locked":
            raise _story_error(409, "CANON_LOCKED", "Canon 已锁定。")
        if not row:
            row = CanonRelation(id=relation_id, created_at=now, updated_at=now)
            session.add(row)
        row.subject_entity_id = str(item.get("subjectEntityId") or item.get("subject_entity_id") or "")
        row.predicate = str(item.get("predicate") or "")
        row.object_entity_id = item.get("objectEntityId") or item.get("object_entity_id")
        row.object_value_json = _dumps(item.get("objectValueJson") or item.get("object_value_json")) if (item.get("objectValueJson") or item.get("object_value_json")) is not None else None
        row.status = str(item.get("status") or row.status or "draft")
        row.revision = int(item.get("revision") or row.revision or 1)
        row.source_document_id = item.get("sourceDocumentId") or item.get("source_document_id")
        row.updated_at = now

    def _upsert_rule(self, session: Session, item: dict[str, Any], now: datetime) -> None:
        rule_code = str(item.get("ruleCode") or item.get("rule_code") or "").strip()
        if not rule_code:
            raise _story_error(422, "CANON_SCHEMA_INVALID", "规则编码不能为空。")
        row = session.scalar(select(CanonRule).where(CanonRule.rule_code == rule_code))
        if row and row.status == "locked":
            raise _story_error(409, "CANON_LOCKED", "Canon 已锁定。")
        if not row:
            row = CanonRule(id=str(uuid4()), rule_code=rule_code, created_at=now, updated_at=now)
            session.add(row)
        row.category = str(item.get("category") or row.category or "general")
        row.statement = str(item.get("statement") or "")
        row.severity = str(item.get("severity") or row.severity or "medium")
        row.constraint_json = _dumps(item.get("constraintJson") or item.get("constraint_json") or {})
        row.status = str(item.get("status") or row.status or "draft")
        row.revision = int(item.get("revision") or row.revision or 1)
        row.source_document_id = item.get("sourceDocumentId") or item.get("source_document_id")
        row.updated_at = now

    def _mirror_canon_markdown(self, session: Session, folder_path: str) -> None:
        doc = session.get(CanonDocument, "story-core")
        if not doc:
            return
        folder = Path(folder_path)
        mirror = folder / "canon" / "story-core.md"
        _atomic_write_text(mirror, doc.content_markdown or f"# {doc.title}\n")

    def _resolve_canon_target(self, session: Session, target_kind: str, target_id: str):
        mapping = {
            "document": CanonDocument,
            "entity_type": CanonEntityType,
            "entity": CanonEntity,
            "relation": CanonRelation,
            "rule": CanonRule,
        }
        model = mapping.get(target_kind)
        return session.get(model, target_id) if model else None

    def _apply_canon_target_patch(self, target: Any, payload: dict[str, Any]) -> None:
        if isinstance(target, CanonDocument):
            target.title = str(payload.get("title") or target.title)
            target.kind = str(payload.get("kind") or target.kind)
            target.content_markdown = str(payload.get("contentMarkdown") or payload.get("content_markdown") or target.content_markdown)
        elif isinstance(target, CanonEntityType):
            schema_json = payload.get("schemaJson") or payload.get("schema_json") or _loads(target.schema_json, {})
            if not _canon_schema_is_safe(schema_json):
                raise _story_error(422, "CANON_SCHEMA_INVALID", "实体类型 Schema 不安全。")
            target.display_name = str(payload.get("displayName") or payload.get("display_name") or target.display_name)
            target.schema_json = _dumps(schema_json)
        elif isinstance(target, CanonEntity):
            target.aliases_json = _dumps(payload.get("aliasesJson") or payload.get("aliases_json") or _loads(target.aliases_json, []))
            attrs = payload.get("attributesJson") or payload.get("attributes_json") or _loads(target.attributes_json, {})
            entity_type = session.get(CanonEntityType, target.entity_type_id) if hasattr(target, "entity_type_id") else None
            if entity_type and not _json_schema_subset_valid(_loads(entity_type.schema_json, {}), attrs):
                raise _story_error(422, "CANON_SCHEMA_INVALID", "实体属性不符合 Schema。")
            target.attributes_json = _dumps(attrs)
        elif isinstance(target, CanonRelation):
            target.predicate = str(payload.get("predicate") or target.predicate)
            target.object_value_json = _dumps(payload.get("objectValueJson") or payload.get("object_value_json")) if (payload.get("objectValueJson") or payload.get("object_value_json")) is not None else target.object_value_json
        elif isinstance(target, CanonRule):
            target.statement = str(payload.get("statement") or target.statement)
            target.severity = str(payload.get("severity") or target.severity)
            target.constraint_json = _dumps(payload.get("constraintJson") or payload.get("constraint_json") or _loads(target.constraint_json, {}))
        else:
            raise _story_error(422, "CANON_TARGET_NOT_FOUND", "不支持的 Canon 目标。")

    def _materialize_state_payload(self, session: Session, project_id: str, data: dict[str, Any], source_version_id: str, now: datetime) -> None:
        entities_by_name: dict[str, StoryEntity] = {}
        for entity_item in data.get("entities", []) if isinstance(data.get("entities"), list) else []:
            if not isinstance(entity_item, dict):
                continue
            canonical_name = str(entity_item.get("canonicalName") or entity_item.get("canonical_name") or "").strip()
            if not canonical_name:
                continue
            entity_type_id = str(entity_item.get("entityTypeId") or entity_item.get("entity_type_id") or "")
            row = session.scalar(select(StoryEntity).where(StoryEntity.project_id == project_id, StoryEntity.canonical_name == canonical_name))
            if not row:
                row = StoryEntity(
                    id=str(uuid4()),
                    project_id=project_id,
                    entity_type_id=entity_type_id,
                    canonical_name=canonical_name,
                    status="active",
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            row.entity_type_id = entity_type_id
            row.aliases_json = _dumps([alias for alias in (entity_item.get("aliases") or []) if isinstance(alias, str)])
            row.attributes_json = _dumps(entity_item.get("attributes") or {})
            row.status = "active"
            row.source_version_id = source_version_id
            row.updated_at = now
            entities_by_name[canonical_name] = row

        for fact_item in data.get("facts", []) if isinstance(data.get("facts"), list) else []:
            if not isinstance(fact_item, dict):
                continue
            entity_name = str(fact_item.get("entity") or fact_item.get("entityName") or "").strip()
            field_path = str(fact_item.get("fieldPath") or fact_item.get("field_path") or "").strip()
            if not entity_name or not field_path or entity_name not in entities_by_name:
                continue
            entity = entities_by_name[entity_name]
            current = session.scalars(select(StateFact).where(StateFact.project_id == project_id, StateFact.entity_id == entity.id, StateFact.field_path == field_path, StateFact.is_current.is_(True))).all()
            for existing in current:
                existing.is_current = False
                existing.valid_to = now
                existing.updated_at = now
            fact = StateFact(
                id=str(uuid4()),
                project_id=project_id,
                entity_id=entity.id,
                field_path=field_path,
                value_json=_dumps(fact_item.get("value")),
                valid_from=now,
                valid_to=None,
                source_version_id=source_version_id,
                confidence=float(fact_item.get("confidence") or 1.0),
                is_current=True,
                revision=1,
                created_at=now,
                updated_at=now,
            )
            session.add(fact)
            if current:
                session.add(self.service._audit("state.conflict_detected", "state_fact", entity.id, {"fieldPath": field_path, "sourceVersionId": source_version_id}, source_version_id))
            session.add(StateDelta(
                id=str(uuid4()),
                project_id=project_id,
                event_id=None,
                field_path=field_path,
                before_json=current[0].value_json if current else None,
                after_json=fact.value_json,
                source_version_id=source_version_id,
                status="official",
                revision=1,
                created_at=now,
                updated_at=now,
            ))

        for event_item in data.get("events", []) if isinstance(data.get("events"), list) else []:
            if not isinstance(event_item, dict):
                continue
            event = StoryEvent(
                id=str(uuid4()),
                project_id=project_id,
                event_order=int(event_item.get("eventOrder") or event_item.get("event_order") or 0),
                occurred_at=now,
                location=str(event_item.get("location") or ""),
                participants_json=_dumps([participant for participant in event_item.get("participants", []) if isinstance(participant, str)]),
                summary=str(event_item.get("summary") or ""),
                source_version_id=source_version_id,
                revision=1,
                created_at=now,
                updated_at=now,
            )
            session.add(event)

        for item in data.get("foreshadows", []) if isinstance(data.get("foreshadows"), list) else []:
            if not isinstance(item, dict):
                continue
            foreshadow = Foreshadow(
                id=str(uuid4()),
                project_id=project_id,
                code=str(item.get("code") or f"foreshadow-{uuid4().hex[:8]}"),
                label=str(item.get("label") or item.get("name") or "伏笔"),
                description=str(item.get("description") or ""),
                status=str(item.get("status") or "pending"),
                earliest_chapter=item.get("earliestChapter") or item.get("earliest_chapter"),
                target_chapter=item.get("targetChapter") or item.get("target_chapter"),
                latest_chapter=item.get("latestChapter") or item.get("latest_chapter"),
                source_version_id=source_version_id,
                evidence_json=_dumps(item.get("evidence") or []),
                revision=1,
                created_at=now,
                updated_at=now,
            )
            session.add(foreshadow)

        for item in data.get("boundaries", []) if isinstance(data.get("boundaries"), list) else []:
            if not isinstance(item, dict):
                continue
            entity_name = str(item.get("entity") or item.get("entityName") or "").strip()
            entity = entities_by_name.get(entity_name)
            if not entity:
                continue
            boundary = KnowledgeBoundary(
                id=str(uuid4()),
                project_id=project_id,
                entity_id=entity.id,
                source_version_id=source_version_id,
                knowledge_json=_dumps(item.get("knowledge") or {}),
                status=str(item.get("status") or "active"),
                revision=1,
                created_at=now,
                updated_at=now,
            )
            session.add(boundary)

    def _create_state_snapshot(self, session: Session, project_id: str, source_version_id: str, data: dict[str, Any], now: datetime) -> StateSnapshot:
        next_number = (session.scalar(select(StateSnapshot.snapshot_number).where(StateSnapshot.project_id == project_id).order_by(StateSnapshot.snapshot_number.desc())) or 0) + 1
        summary = {
            "entityCount": len(data.get("entities", [])) if isinstance(data.get("entities"), list) else 0,
            "factCount": len(data.get("facts", [])) if isinstance(data.get("facts"), list) else 0,
            "eventCount": len(data.get("events", [])) if isinstance(data.get("events"), list) else 0,
            "foreshadowCount": len(data.get("foreshadows", [])) if isinstance(data.get("foreshadows"), list) else 0,
        }
        snapshot = StateSnapshot(
            id=str(uuid4()),
            project_id=project_id,
            snapshot_number=next_number,
            source_version_id=source_version_id,
            summary_json=_dumps(summary),
            checksum=_stable_digest({"sourceVersionId": source_version_id, **summary}),
            revision=1,
            created_at=now,
            updated_at=now,
        )
        session.add(snapshot)
        return snapshot

    def _rebuild_retrieval_index(self, session: Session, project_id: str, now: datetime) -> None:
        session.execute(text("DELETE FROM retrieval_index_entries WHERE project_id = :project_id"), {"project_id": project_id})
        session.execute(text("DELETE FROM retrieval_fts WHERE project_id = :project_id"), {"project_id": project_id})
        entries: list[dict[str, Any]] = []
        for doc in session.scalars(select(CanonDocument).where(CanonDocument.kind == "story-core", CanonDocument.status == "locked")).all():
            entries.append({"kind": "canon_document", "title": doc.title, "content": doc.content_markdown, "source_version_id": None, "entity_id": None, "checksum": _stable_digest(doc.content_markdown), "source_status": "official"})
        for entity in session.scalars(select(StoryEntity).where(StoryEntity.project_id == project_id, StoryEntity.status == "active")).all():
            facts = session.scalars(select(StateFact).where(StateFact.project_id == project_id, StateFact.entity_id == entity.id, StateFact.is_current.is_(True))).all()
            content = " ".join([entity.canonical_name] + [f"{fact.field_path}:{_loads(fact.value_json, None)}" for fact in facts])
            entries.append({"kind": "entity", "title": entity.canonical_name, "content": content, "source_version_id": entity.source_version_id, "entity_id": entity.id, "checksum": _stable_digest(content), "source_status": "official"})
        for event in session.scalars(select(StoryEvent).where(StoryEvent.project_id == project_id)).all():
            entries.append({"kind": "event", "title": event.summary[:120] or event.location or event.id, "content": event.summary, "source_version_id": event.source_version_id, "entity_id": None, "checksum": _stable_digest(event.summary), "source_status": "official"})
        for foreshadow in session.scalars(select(Foreshadow).where(Foreshadow.project_id == project_id, Foreshadow.status != "superseded")).all():
            entries.append({"kind": "foreshadow", "title": foreshadow.label, "content": foreshadow.description, "source_version_id": foreshadow.source_version_id, "entity_id": None, "checksum": _stable_digest(foreshadow.description), "source_status": "official"})

        session.execute(text("DELETE FROM retrieval_index_entries WHERE project_id = :project_id"), {"project_id": project_id})
        for entry in entries:
            entry_id = entry.get("entry_id") or str(uuid4())
            result = session.execute(text("""
                INSERT INTO retrieval_index_entries(entry_id, project_id, kind, title, content, source_version_id, entity_id, checksum, source_status, created_at, updated_at)
                VALUES(:entry_id, :project_id, :kind, :title, :content, :source_version_id, :entity_id, :checksum, :source_status, :created_at, :updated_at)
            """), {**entry, "entry_id": entry_id, "project_id": project_id, "created_at": now, "updated_at": now})
            rowid = result.lastrowid
            session.execute(text("""
                INSERT INTO retrieval_fts(rowid, project_id, kind, title, content, source_version_id, entity_id, checksum, source_status)
                VALUES(:rowid, :project_id, :kind, :title, :content, :source_version_id, :entity_id, :checksum, :source_status)
            """), {**entry, "rowid": rowid, "entry_id": entry_id, "project_id": project_id})

        state = session.get(RetrievalIndexState, project_id)
        if not state:
            state = RetrievalIndexState(project_id=project_id, updated_at=now)
            session.add(state)
        state.last_rebuilt_at = now
        state.indexed_count = len(entries)
        state.vector_backend = "sqlite-local"
        state.vector_available = True
        state.checksum = _stable_digest(entries)
        state.updated_at = now

    def _exact_retrieval_hits(self, session: Session, project_id: str, query: str, limit: int) -> list[dict[str, Any]]:
        lowered = query.lower()
        hits: list[dict[str, Any]] = []
        for entity in session.scalars(select(StoryEntity).where(StoryEntity.project_id == project_id, StoryEntity.status == "active")).all():
            aliases = _loads(entity.aliases_json, [])
            if lowered in entity.canonical_name.lower() or any(lowered in str(alias).lower() for alias in aliases):
                hits.append(self._retrieval_hit({
                    "id": entity.id,
                    "kind": "entity",
                    "title": entity.canonical_name,
                    "content": _dumps(_loads(entity.attributes_json, {})),
                    "source_version_id": entity.source_version_id,
                    "entity_id": entity.id,
                    "checksum": _stable_digest(entity.canonical_name),
                    "source_status": "official",
                    "score": 1.0,
                }))
        return hits[:limit]

    def _fts_retrieval_hits(self, session: Session, project_id: str, query: str, limit: int) -> list[dict[str, Any]]:
        safe_query = re.sub(r"[^\w\u4e00-\u9fff]+", " ", query).strip()
        if not safe_query:
            return []
        rows = session.execute(text("""
            SELECT retrieval_index_entries.entry_id AS entry_id,
                   retrieval_fts.kind,
                   retrieval_fts.title,
                   retrieval_fts.content,
                   retrieval_fts.source_version_id,
                   retrieval_fts.entity_id,
                   retrieval_fts.checksum,
                   retrieval_fts.source_status,
                   bm25(retrieval_fts) AS score
            FROM retrieval_fts
            JOIN retrieval_index_entries ON retrieval_index_entries.rowid = retrieval_fts.rowid
            WHERE retrieval_fts MATCH :query AND retrieval_fts.project_id = :project_id
            ORDER BY score
            LIMIT :limit
        """), {"query": safe_query, "project_id": project_id, "limit": limit}).mappings().all()
        return [self._retrieval_hit({"id": row["entry_id"], **dict(row)}) for row in rows]

    def _vector_retrieval_hits(self, session: Session, project_id: str, query: str, limit: int) -> list[dict[str, Any]]:
        tokens = [token for token in re.split(r"\W+", query.lower()) if token]
        if not tokens:
            return []
        rows = session.execute(text("SELECT entry_id, kind, title, content, source_version_id, entity_id, checksum, source_status FROM retrieval_index_entries WHERE project_id = :project_id"), {"project_id": project_id}).mappings().all()
        scored = []
        for row in rows:
            content_tokens = set(re.split(r"\W+", f"{row['title']} {row['content']}".lower()))
            score = len(content_tokens.intersection(tokens)) / max(len(set(tokens)), 1)
            if score > 0:
                data = dict(row)
                data["id"] = data.pop("entry_id")
                data["score"] = round(score, 4)
                scored.append(self._retrieval_hit(data))
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:limit]

    # ------------------------------------------------------------------
    # Dict converters
    # ------------------------------------------------------------------
    def _document_out(self, item: CanonDocument) -> CanonDocumentOut:
        return CanonDocumentOut(id=item.id, title=item.title, kind=item.kind, content_markdown=item.content_markdown, status=item.status, revision=item.revision, locked_at=item.locked_at)

    def _entity_type_out(self, item: CanonEntityType) -> CanonEntityTypeOut:
        return CanonEntityTypeOut(id=item.id, name=item.name, display_name=item.display_name, schema_data=_loads(item.schema_json, {}), is_system=item.is_system, status=item.status, revision=item.revision, source_document_id=item.source_document_id, locked_at=item.locked_at)

    def _canon_entity_out(self, item: CanonEntity) -> CanonEntityOut:
        return CanonEntityOut(id=item.id, entity_type_id=item.entity_type_id, canonical_name=item.canonical_name, aliases=_loads(item.aliases_json, []), attributes=_loads(item.attributes_json, {}), status=item.status, revision=item.revision, source_document_id=item.source_document_id, locked_at=item.locked_at)

    def _relation_out(self, item: CanonRelation) -> CanonRelationOut:
        return CanonRelationOut(id=item.id, subject_entity_id=item.subject_entity_id, predicate=item.predicate, object_entity_id=item.object_entity_id, object_value=_loads(item.object_value_json, None), status=item.status, revision=item.revision, source_document_id=item.source_document_id, locked_at=item.locked_at)

    def _rule_out(self, item: CanonRule) -> CanonRuleOut:
        return CanonRuleOut(id=item.id, rule_code=item.rule_code, category=item.category, statement=item.statement, severity=item.severity, constraint_json=_loads(item.constraint_json, {}), status=item.status, revision=item.revision, source_document_id=item.source_document_id, locked_at=item.locked_at)

    def _change_request_out(self, item: CanonChangeRequest) -> CanonChangeRequestOut:
        return CanonChangeRequestOut(id=item.id, project_id=item.project_id, target_kind=item.target_kind, target_id=item.target_id, reason=item.reason, impact_summary=item.impact_summary, before_json=_loads(item.before_json, None), after_json=_loads(item.after_json, None), status=item.status, revision=item.revision, created_at=item.created_at, updated_at=item.updated_at)

    def _source_version_out(self, item: SourceVersion) -> SourceVersionOut:
        return SourceVersionOut(id=item.id, project_id=item.project_id, source_id=item.source_id, version_number=item.version_number, source_kind=item.source_kind, status=item.status, checksum=item.checksum, summary=item.summary, revision=item.revision, created_at=item.created_at, updated_at=item.updated_at)

    def _story_entity_out(self, item: StoryEntity, session: Session) -> StoryEntityOut:
        return StoryEntityOut(id=item.id, project_id=item.project_id, entity_type_id=item.entity_type_id, canonical_name=item.canonical_name, aliases=_loads(item.aliases_json, []), attributes=_loads(item.attributes_json, {}), status=item.status, revision=item.revision, source_document_id=item.source_document_id, source_version_id=item.source_version_id)

    def _state_fact_out(self, item: StateFact) -> StateFactOut:
        return StateFactOut(id=item.id, entity_id=item.entity_id, field_path=item.field_path, value_json=_loads(item.value_json, None), valid_from=item.valid_from, valid_to=item.valid_to, source_version_id=item.source_version_id, confidence=item.confidence, is_current=item.is_current, revision=item.revision)

    def _story_event_out(self, item: StoryEvent) -> StoryEventOut:
        return StoryEventOut(id=item.id, event_order=item.event_order, occurred_at=item.occurred_at, location=item.location, participants=_loads(item.participants_json, []), summary=item.summary, source_version_id=item.source_version_id, revision=item.revision)

    def _state_delta_out(self, item: StateDelta) -> StateDeltaOut:
        return StateDeltaOut(id=item.id, event_id=item.event_id, field_path=item.field_path, before_json=_loads(item.before_json, None), after_json=_loads(item.after_json, None), source_version_id=item.source_version_id, status=item.status, revision=item.revision)

    def _foreshadow_out(self, item: Foreshadow) -> ForeshadowOut:
        return ForeshadowOut(id=item.id, code=item.code, label=item.label, description=item.description, status=item.status, earliest_chapter=item.earliest_chapter, target_chapter=item.target_chapter, latest_chapter=item.latest_chapter, source_version_id=item.source_version_id, evidence=_loads(item.evidence_json, []), revision=item.revision, resolved_at=item.resolved_at)

    def _knowledge_boundary_out(self, item: KnowledgeBoundary) -> KnowledgeBoundaryOut:
        return KnowledgeBoundaryOut(id=item.id, entity_id=item.entity_id, source_version_id=item.source_version_id, knowledge_json=_loads(item.knowledge_json, {}), status=item.status, revision=item.revision)

    def _state_snapshot_out(self, item: StateSnapshot) -> StateSnapshotOut:
        return StateSnapshotOut(id=item.id, snapshot_number=item.snapshot_number, source_version_id=item.source_version_id, summary_json=_loads(item.summary_json, {}), checksum=item.checksum, revision=item.revision, created_at=item.created_at)

    def _retrieval_status_out(self, project_id: str, state: RetrievalIndexState) -> RetrievalStatus:
        return RetrievalStatus(project_id=project_id, indexed_count=state.indexed_count, last_rebuilt_at=state.last_rebuilt_at, vector_backend=state.vector_backend, vector_available=state.vector_available, checksum=state.checksum)

    def _retrieval_hit(self, row: dict[str, Any]) -> dict[str, Any]:
        return RetrievalHit(
            id=row["id"],
            kind=row["kind"],
            title=row["title"],
            content=row.get("content", ""),
            source_version_id=row.get("source_version_id"),
            entity_id=row.get("entity_id"),
            checksum=row.get("checksum", ""),
            score=float(row.get("score", 0.0)),
            source_status=row.get("source_status", "official"),
        ).model_dump(mode="json", by_alias=True)

    def _context_item_out(self, row: dict[str, Any]) -> ContextTraceItemOut:
        return ContextTraceItemOut(kind=row["kind"], title=row["title"], source_version_id=row.get("sourceVersionId"), priority=row["priority"], token_estimate=row["tokenEstimate"], reason=row["reason"], included=row["included"])

    def _mirror_canon_markdown_for_project(self, project_id: str, folder_path: str) -> None:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            self._mirror_canon_markdown(session, folder_path)
