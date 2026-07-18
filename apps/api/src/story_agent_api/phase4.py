from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol
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
    ModelRun,
    PlanNode,
    ProjectMeta,
    RetrievalIndexState,
    SourceVersion,
    StateDelta,
    StateFact,
    StateSnapshot,
    StoryEvent,
    StoryEntity,
)


class VectorSearchBackend(Protocol):
    """Small injectable boundary for vector-like retrieval.

    Phase four deliberately ships with a deterministic local implementation so
    tests and offline use do not depend on an embedding provider. A later
    provider can implement this protocol without changing the retrieval merge.
    """

    name: str

    @property
    def available(self) -> bool: ...

    def upsert(self, project_id: str, entries: list[dict[str, Any]]) -> None: ...

    def delete_source_version(self, project_id: str, source_version_id: str) -> None: ...

    def rebuild(self, project_id: str, entries: list[dict[str, Any]]) -> None: ...

    def search(self, rows: list[dict[str, Any]], query: str, limit: int) -> list[dict[str, Any]]: ...


class LocalTokenVectorBackend:
    name = "local-token-vector-v1"

    @property
    def available(self) -> bool:
        return True

    def upsert(self, project_id: str, entries: list[dict[str, Any]]) -> None:
        return

    def delete_source_version(self, project_id: str, source_version_id: str) -> None:
        return

    def rebuild(self, project_id: str, entries: list[dict[str, Any]]) -> None:
        return

    @staticmethod
    def _features(value: str) -> set[str]:
        normalized = re.sub(r"\s+", "", value.lower())
        words = {part for part in re.split(r"\W+", value.lower()) if part}
        # Character n-grams keep the deterministic fallback useful for Chinese.
        grams = {normalized[index:index + 2] for index in range(max(0, len(normalized) - 1))}
        return words | grams

    def search(self, rows: list[dict[str, Any]], query: str, limit: int) -> list[dict[str, Any]]:
        query_features = self._features(query)
        if not query_features:
            return []
        scored: list[dict[str, Any]] = []
        for row in rows:
            content_features = self._features(f"{row['title']} {row['content']}")
            score = len(query_features & content_features) / max(len(query_features | content_features), 1)
            if score >= 0.12:
                item = dict(row)
                item["id"] = item.pop("entry_id")
                item["score"] = round(score, 4)
                scored.append(item)
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:limit]
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

    def __init__(self, service: Any, vector_backend: VectorSearchBackend | None = None):
        self.service = service
        self.vector_backend = vector_backend or LocalTokenVectorBackend()

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
            index_state = session.get(RetrievalIndexState, project_id)
            if index_state is None:
                session.add(RetrievalIndexState(
                    project_id=project_id,
                    last_rebuilt_at=None,
                    indexed_count=0,
                    vector_backend=self.vector_backend.name,
                    vector_available=self.vector_backend.available,
                    checksum="",
                    updated_at=now,
                ))
            elif index_state.last_rebuilt_at is None:
                index_state.vector_backend = self.vector_backend.name
                index_state.vector_available = self.vector_backend.available
                index_state.updated_at = now

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
        self._mirror_canon_markdown_safely(project.id, project.folder_path)
        return self.get_canon(project_id)

    def analyze_canon(self, project_id: str, payload: CanonAnalyzeRequest, request_id: str) -> dict[str, Any]:
        if payload.project_id != project_id:
            raise _story_error(422, "PROJECT_ID_MISMATCH", "路径与请求体中的作品 ID 不一致。")
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
                "content": (
                    "你是 Story Agent 的 Canon 分析器。只输出合法 JSON object，不要 Markdown 或解释。"
                    "顶层字段固定为 documents、entityTypes、entities、relations、rules。"
                    "documents 和 entityTypes 通常输出空数组；不得改写用户原始故事核心。"
                    "entities 每项使用 canonicalName、entityTypeName、aliasesJson、attributesJson，"
                    "entityTypeName 只能优先使用 person、location、organization、item、ability、event、intel、foreshadow、time_point。"
                    "relations 每项使用 subjectCanonicalName、predicate，以及 objectCanonicalName 或 objectValueJson；"
                    "不要虚构数据库 UUID。rules 每项使用 ruleCode、category、statement、severity、constraintJson。"
                    "只提取来源文本明确支持的设定，保留能力代价、知识边界、时间窗口和禁止提前揭示事项。"
                    "最多输出 20 个实体、20 条关系和 16 条规则；合并重复信息，所有字段保持简洁，避免复述整篇原文。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps({
                    "projectId": project.id,
                    "projectTitle": project.title,
                    "currentCanon": self.get_canon(project.id),
                    "sourceText": payload.source_text,
                    "title": payload.title,
                }, ensure_ascii=False),
            },
        ]
        sections = [
            (
                "entities_relations",
                "只输出 entities 和 relations 两个数组。最多 20 个实体、20 条关系；attributesJson 每个字段保持短句。不要输出 rules、documents 或 entityTypes。",
                ("entities", "relations"),
            ),
            (
                "rules",
                "只输出 rules 数组。最多 16 条规则，合并重复规则；constraintJson 只保存机器检查需要的关键边界。不要输出 entities、relations、documents 或 entityTypes。",
                ("rules",),
            ),
        ]
        extracted: dict[str, list[dict[str, Any]]] = {"entities": [], "relations": [], "rules": []}
        attempts_used: dict[str, int] = {}
        import asyncio

        for section_name, instruction, accepted_keys in sections:
            last_error: Exception | None = None
            for attempt in range(2):
                model_run_id = str(uuid4())
                started_clock = time.perf_counter()
                with self.service.db.project_write(project.id, project.folder_path) as session:
                    session.add(ModelRun(
                        id=model_run_id,
                        session_id=None,
                        role=f"architect:{section_name}",
                        provider_id=provider.id,
                        provider_name=provider.name,
                        model_config_id=model.id,
                        model_id=model.model_id,
                        status="running",
                        request_id=request_id,
                        retry_count=attempt,
                        started_at=datetime.now(timezone.utc),
                    ))
                try:
                    section_messages = prompt_messages + [{"role": "system", "content": instruction}]
                    if attempt:
                        section_messages.append({
                            "role": "system",
                            "content": "上一次输出无效。请严格缩短内容，只返回本子任务要求的合法 JSON object。",
                        })
                    result = asyncio.run(provider_client.complete_chat({
                        "model": model.model_id,
                        "messages": section_messages,
                        "temperature": min(float(model.temperature), 0.2),
                        "max_tokens": min(model.max_output_tokens, 8192),
                        "response_format": {"type": "json_object"},
                    }))
                    data = json.loads(result.text or "")
                    if not isinstance(data, dict):
                        raise ValueError("not object")
                    for key in accepted_keys:
                        value = data.get(key, [])
                        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
                            raise ValueError(f"invalid {key}")
                        extracted[key] = value
                    self._finish_canon_model_run(
                        project.id,
                        project.folder_path,
                        model_run_id,
                        "succeeded",
                        provider_client.last_result,
                        model,
                        started_clock,
                    )
                    attempts_used[section_name] = attempt + 1
                    break
                except (json.JSONDecodeError, ValueError) as exc:
                    last_error = exc
                    self._finish_canon_model_run(
                        project.id,
                        project.folder_path,
                        model_run_id,
                        "failed",
                        provider_client.last_result,
                        model,
                        started_clock,
                        "invalid_json",
                        {"section": section_name, "attempt": attempt + 1},
                    )
                    continue
                except ModelProviderError as exc:
                    self._finish_canon_model_run(
                        project.id,
                        project.folder_path,
                        model_run_id,
                        "failed",
                        provider_client.last_result,
                        model,
                        started_clock,
                        exc.code,
                        {"section": section_name, "attempt": attempt + 1, "retryable": exc.retryable},
                    )
                    raise _story_error(502, "MODEL_PROVIDER_ERROR", exc.message, {
                        "providerCode": exc.code,
                        "section": section_name,
                    }) from exc
            else:
                raise _story_error(422, "CANON_ANALYSIS_INVALID", "Canon 分析器未能输出有效 JSON。", {
                    "section": section_name,
                    "error": str(last_error) if last_error else "invalid model output",
                })

        entity_by_name = {
            str(item.get("canonicalName") or item.get("canonical_name") or "").strip(): item
            for item in extracted["entities"]
            if str(item.get("canonicalName") or item.get("canonical_name") or "").strip()
        }
        relation_by_key = {
            json.dumps({
                "subject": item.get("subjectCanonicalName") or item.get("subject_canonical_name") or item.get("subject"),
                "predicate": item.get("predicate"),
                "object": item.get("objectCanonicalName") or item.get("object_canonical_name") or item.get("object"),
                "value": item.get("objectValueJson") if "objectValueJson" in item else item.get("object_value_json"),
            }, ensure_ascii=False, sort_keys=True): item
            for item in extracted["relations"]
        }
        rule_by_code = {
            str(item.get("ruleCode") or item.get("rule_code") or "").strip(): item
            for item in extracted["rules"]
            if str(item.get("ruleCode") or item.get("rule_code") or "").strip()
        }
        draft = CanonDraftUpdate(
            entities=list(entity_by_name.values()),
            relations=list(relation_by_key.values()),
            rules=list(rule_by_code.values()),
        )
        try:
            with self.service.db.project_write(project.id, project.folder_path) as session:
                if session.scalar(select(CanonDocument).where(CanonDocument.status == "locked")):
                    raise _story_error(409, "CANON_LOCKED", "Canon 已锁定，只能通过变更申请修改。")
                now = datetime.now(timezone.utc)
                for entry in draft.entities:
                    self._upsert_entity(session, entry, now)
                for entry in draft.relations:
                    self._upsert_relation(session, entry, now)
                for entry in draft.rules:
                    self._upsert_rule(session, entry, now)
                session.add(self.service._audit("canon.analysis_completed", "canon_document", "story-core", {
                    "requestId": request_id,
                    "sections": attempts_used,
                    "reversible": False,
                }, request_id))
            self._mirror_canon_markdown_safely(project.id, project.folder_path)
            return self.get_canon(project_id)
        except Exception as exc:
            from .services import StoryError

            if isinstance(exc, StoryError):
                raise
            raise _story_error(422, "CANON_ANALYSIS_INVALID", f"Canon 分析失败: {exc}") from exc

    def _finish_canon_model_run(
        self,
        project_id: str,
        folder_path: str,
        run_id: str,
        status: str,
        result: Any,
        model: Any,
        started_clock: float,
        error_code: str | None = None,
        diagnostic: dict[str, Any] | None = None,
    ) -> None:
        with self.service.db.project_write(project_id, folder_path) as session:
            run = session.get(ModelRun, run_id)
            if not run:
                return
            run.status = status
            run.prompt_tokens = result.prompt_tokens
            run.completion_tokens = result.completion_tokens
            run.total_tokens = result.total_tokens
            run.estimated_cost = (
                ((result.prompt_tokens or 0) * (model.input_price_per_million or 0.0))
                + ((result.completion_tokens or 0) * (model.output_price_per_million or 0.0))
            ) / 1_000_000
            run.retry_count = result.retry_count
            run.duration_ms = int((time.perf_counter() - started_clock) * 1000)
            run.error_code = error_code
            run.diagnostic_json = _dumps(diagnostic) if diagnostic else None
            if result.actual_model:
                run.model_id = result.actual_model
            run.ended_at = datetime.now(timezone.utc)

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
            # A Canon created through the market-research incubator has a
            # stronger handoff gate: a human must approve all three opening
            # experiment chapters before the document becomes authoritative.
            # Legacy and manually-authored Canon retain the original flow.
            self.service.phase13.assert_canon_lockable(session, project.id, root)
            now = datetime.now(timezone.utc)
            before = {"rootRevision": root.revision, "rootStatus": root.status}
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
        self._mirror_canon_markdown_safely(project.id, project.folder_path)
        return self.get_canon(project_id)

    def create_canon_change_request(self, project_id: str, payload: CanonChangeRequestCreate, request_id: str) -> dict[str, Any]:
        if payload.project_id != project_id:
            raise _story_error(422, "PROJECT_ID_MISMATCH", "路径与请求体中的作品 ID 不一致。")
        if not isinstance(payload.after_json, dict) or not payload.after_json:
            raise _story_error(422, "CANON_CHANGE_INVALID", "Canon 变更申请必须包含非空 afterJson。")
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            root = session.get(CanonDocument, "story-core")
            if not root or root.status != "locked":
                raise _story_error(409, "CANON_NOT_LOCKED", "Canon 锁定后才能提交变更申请。")
            target = self._resolve_canon_target(session, payload.target_kind, payload.target_id)
            if target is None:
                raise _story_error(404, "CANON_TARGET_NOT_FOUND", "Canon 目标不存在。")
            item = CanonChangeRequest(
                id=str(uuid4()),
                project_id=project_id,
                target_kind=payload.target_kind,
                target_id=payload.target_id,
                reason=payload.reason,
                impact_summary=payload.impact_summary,
                before_json=_dumps(self._canon_target_snapshot(target)),
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
            self._apply_canon_target_patch(session, target, _loads(item.after_json, {}))
            item.status = "accepted"
            item.revision += 1
            item.updated_at = datetime.now(timezone.utc)
            target.updated_at = datetime.now(timezone.utc)
            if hasattr(target, "revision"):
                target.revision = int(getattr(target, "revision", 1)) + 1
            if hasattr(target, "locked_at"):
                target.locked_at = datetime.now(timezone.utc)
            if hasattr(target, "status"):
                target.status = "locked"
            session.add(self.service._audit("canon.change_request.applied", item.target_kind, item.target_id, {"changeRequestId": item.id}, request_id))
            self._rebuild_retrieval_index(session, project.id, datetime.now(timezone.utc))
        self._mirror_canon_markdown_safely(project.id, project.folder_path)
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
            duplicate = session.scalar(select(SourceVersion).where(
                SourceVersion.project_id == project.id,
                SourceVersion.source_id == payload.source_id,
                SourceVersion.version_number == payload.version_number,
            ))
            if duplicate:
                raise _story_error(409, "SOURCE_VERSION_EXISTS", "同一来源的版本号已存在。", {"sourceVersionId": duplicate.id})
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
        try:
            with self.service.db.project_write(project.id, project.folder_path) as session:
                candidate = session.get(SourceVersion, candidate_id)
                if not candidate or candidate.project_id != project.id:
                    raise _story_error(404, "SOURCE_VERSION_NOT_FOUND", "来源版本不存在。")
                if candidate.revision != payload.expected_revision:
                    raise _story_error(409, "STATE_REVISION_CONFLICT", "来源版本已变化。", {"currentRevision": candidate.revision})
                if candidate.status not in {"candidate", "official"}:
                    raise _story_error(409, "SOURCE_VERSION_NOT_OFFICIAL", "来源版本不处于可提交状态。")
                if candidate.status == "official":
                    return self._source_version_out(candidate).model_dump(mode="json", by_alias=True)
                data = _loads(candidate.payload_json, {})
                now = datetime.now(timezone.utc)
                self._validate_state_payload(session, project.id, data)
                self._materialize_state_payload(session, project.id, data, candidate.id, now)
                candidate.status = "official"
                candidate.revision += 1
                candidate.updated_at = now
                snapshot = self._create_state_snapshot(session, project.id, candidate.id, data, now)
                self._rebuild_retrieval_index(session, project.id, now)
                session.add(self.service._audit("state.candidate.committed", "source_version", candidate.id, {"snapshotId": snapshot.id, "requestId": request_id}, request_id))
                return self._source_version_out(candidate).model_dump(mode="json", by_alias=True)
        except Exception as exc:
            from .services import StoryError

            if isinstance(exc, StoryError) and exc.code == "STATE_FACT_CONFLICT":
                with self.service.db.project_write(project.id, project.folder_path) as session:
                    session.add(self.service._audit(
                        "state.conflict_detected",
                        "source_version",
                        candidate_id,
                        {**exc.details, "requestId": request_id},
                        request_id,
                    ))
            raise

    def supersede_source_version(self, source_version_id: str, payload: SourceVersionSupersede, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(payload.project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            source_version = session.get(SourceVersion, source_version_id)
            if not source_version:
                raise _story_error(404, "SOURCE_VERSION_NOT_FOUND", "来源版本不存在。")
            if source_version.project_id != project.id:
                raise _story_error(404, "SOURCE_VERSION_NOT_FOUND", "来源版本不存在。")
            if source_version.revision != payload.expected_revision:
                raise _story_error(409, "STATE_REVISION_CONFLICT", "来源版本已变化。")
            if source_version.status != "official":
                raise _story_error(409, "SOURCE_VERSION_NOT_OFFICIAL", "只有正式来源版本可以作废。")
            now = datetime.now(timezone.utc)
            source_version.status = "superseded"
            source_version.revision += 1
            source_version.updated_at = now
            affected_fact_keys: set[tuple[str, str]] = set()
            for fact in session.scalars(select(StateFact).where(StateFact.source_version_id == source_version_id)).all():
                affected_fact_keys.add((fact.entity_id, fact.field_path))
            for model in (StateFact, StateDelta, Foreshadow, KnowledgeBoundary):
                for row in session.scalars(select(model).where(getattr(model, "source_version_id") == source_version_id)).all():
                    if hasattr(row, "status"):
                        row.status = "superseded"
                    if hasattr(row, "is_current"):
                        row.is_current = False
                    if hasattr(row, "valid_to") and getattr(row, "valid_to") is None:
                        row.valid_to = now
                    if hasattr(row, "updated_at"):
                        row.updated_at = now
            # Replay the latest still-official fact for every invalidated field.
            for entity_id, field_path in affected_fact_keys:
                previous = session.scalar(
                    select(StateFact)
                    .join(SourceVersion, SourceVersion.id == StateFact.source_version_id)
                    .where(
                        StateFact.project_id == project.id,
                        StateFact.entity_id == entity_id,
                        StateFact.field_path == field_path,
                        StateFact.source_version_id != source_version_id,
                        SourceVersion.status == "official",
                    )
                    .order_by(StateFact.valid_from.desc(), StateFact.created_at.desc())
                )
                if previous:
                    previous.is_current = True
                    previous.valid_to = None
                    previous.updated_at = now
            for entity in session.scalars(select(StoryEntity).where(StoryEntity.source_version_id == source_version_id)).all():
                has_official_fact = session.scalar(
                    select(StateFact.id)
                    .join(SourceVersion, SourceVersion.id == StateFact.source_version_id)
                    .where(StateFact.entity_id == entity.id, SourceVersion.status == "official")
                    .limit(1)
                )
                if not has_official_fact:
                    entity.status = "superseded"
                    entity.updated_at = now
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
            return [self._foreshadow_out(item).model_dump(mode="json", by_alias=True) for item in session.scalars(
                select(Foreshadow)
                .join(SourceVersion, SourceVersion.id == Foreshadow.source_version_id)
                .where(Foreshadow.project_id == project_id, Foreshadow.status != "superseded", SourceVersion.status == "official")
                .order_by(Foreshadow.created_at.asc())
            ).all()]

    def list_timeline(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            events = session.scalars(
                select(StoryEvent).join(SourceVersion, SourceVersion.id == StoryEvent.source_version_id)
                .where(StoryEvent.project_id == project_id, SourceVersion.status == "official")
                .order_by(StoryEvent.event_order.asc(), StoryEvent.occurred_at.asc())
            ).all()
            deltas = session.scalars(
                select(StateDelta).join(SourceVersion, SourceVersion.id == StateDelta.source_version_id)
                .where(StateDelta.project_id == project_id, StateDelta.status == "official", SourceVersion.status == "official")
                .order_by(StateDelta.created_at.asc())
            ).all()
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
            return [self._state_snapshot_out(item).model_dump(mode="json", by_alias=True) for item in session.scalars(
                select(StateSnapshot).join(SourceVersion, SourceVersion.id == StateSnapshot.source_version_id)
                .where(StateSnapshot.project_id == project_id, SourceVersion.status == "official")
                .order_by(StateSnapshot.snapshot_number.asc())
            ).all()]

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
        with self.service.db.project_write(project.id, project.folder_path) as session:
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

            for doc in session.scalars(select(CanonDocument).where(CanonDocument.status == "locked").order_by(CanonDocument.created_at.asc())).all():
                add_item("canon_document", doc.title, doc.content_markdown, 0, "locked canon")
            if payload.selected_node_id:
                node = session.get(PlanNode, payload.selected_node_id)
                if not node:
                    raise _story_error(404, "PLAN_NODE_NOT_FOUND", "所选规划节点不存在。")
                contract = {
                    "title": node.title,
                    "targetChapter": node.target_chapter,
                    "allowedRange": [node.range_min, node.range_max],
                    "prerequisites": _loads(node.prerequisites_json, []),
                    "completionConditions": _loads(node.completion_conditions_json, []),
                    "foreshadows": _loads(node.foreshadows_json, []),
                    "contracts": _loads(node.contracts_json, []),
                }
                add_item("task_contract", node.title, _dumps(contract), 1, "selected planning contract")
            for entity in session.scalars(select(StoryEntity).where(StoryEntity.project_id == project_id, StoryEntity.status == "active").order_by(StoryEntity.created_at.asc())).all():
                facts = session.scalars(select(StateFact).where(StateFact.project_id == project_id, StateFact.entity_id == entity.id, StateFact.is_current.is_(True))).all()
                fact_text = "; ".join(f"{fact.field_path}={_loads(fact.value_json, None)}" for fact in facts)
                add_item("state_fact", entity.canonical_name, fact_text or _dumps(_loads(entity.attributes_json, {})), 2, "current state", entity.source_version_id)
            for boundary in session.scalars(
                select(KnowledgeBoundary).join(SourceVersion, SourceVersion.id == KnowledgeBoundary.source_version_id)
                .where(KnowledgeBoundary.project_id == project_id, KnowledgeBoundary.status == "active", SourceVersion.status == "official")
                .order_by(KnowledgeBoundary.created_at.asc())
            ).all():
                add_item("knowledge_boundary", boundary.entity_id, _dumps(_loads(boundary.knowledge_json, {})), 2, "character knowledge boundary", boundary.source_version_id)
            for foreshadow in session.scalars(
                select(Foreshadow).join(SourceVersion, SourceVersion.id == Foreshadow.source_version_id)
                .where(Foreshadow.project_id == project_id, Foreshadow.status.notin_(["resolved", "superseded"]), SourceVersion.status == "official")
                .order_by(Foreshadow.created_at.asc())
            ).all():
                add_item("foreshadow", foreshadow.label, foreshadow.description, 3, "unresolved foreshadow", foreshadow.source_version_id)
            for event in session.scalars(
                select(StoryEvent).join(SourceVersion, SourceVersion.id == StoryEvent.source_version_id)
                .where(StoryEvent.project_id == project_id, SourceVersion.status == "official")
                .order_by(StoryEvent.event_order.desc(), StoryEvent.occurred_at.desc()).limit(20)
            ).all():
                add_item("event", event.summary[:60] or event.location or event.id, event.summary, 4, "official event", event.source_version_id)
            recent_messages = session.scalars(select(ProjectMeta).where(ProjectMeta.id == project.id)).all()
            if recent_messages:
                meta = recent_messages[0]
                add_item("recent_context", meta.title, f"mode={meta.mode}; chapter={meta.current_chapter}/{meta.total_chapters}", 5, "recent project context")
            retrieval_hits = self.search_retrieval(project_id, RetrievalQuery(query=payload.query or payload.role, limit=8))
            for hit in retrieval_hits:
                add_item("retrieval_hit", hit["title"], hit["content"], 6, "retrieval evidence", hit.get("sourceVersionId"), hit.get("sourceStatus") == "official", hit.get("checksum", ""))

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
            if not trace or trace.project_id != project.id:
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
        is_new = doc is None
        if not doc:
            doc = CanonDocument(id=doc_id, created_at=now, updated_at=now)
            session.add(doc)
        doc.title = str(item.get("title") or doc.title or "Canon")
        doc.kind = str(item.get("kind") or "story-core")
        doc.content_markdown = str(item.get("contentMarkdown") or item.get("content_markdown") or "")
        doc.status = "draft"
        if not is_new:
            doc.revision += 1
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
            if row.is_system and _loads(row.schema_json, {}) == schema_json:
                return
            raise _story_error(409, "CANON_LOCKED", "Canon 已锁定。")
        is_new = row is None
        if not row:
            row = CanonEntityType(id=str(uuid4()), name=name, created_at=now, updated_at=now)
            session.add(row)
        row.display_name = str(item.get("displayName") or item.get("display_name") or name)
        row.schema_json = _dumps(schema_json)
        row.is_system = bool(item.get("isSystem", False))
        row.status = "draft"
        if not is_new:
            row.revision += 1
        row.source_document_id = item.get("sourceDocumentId") or item.get("source_document_id")
        row.updated_at = now

    def _upsert_entity(self, session: Session, item: dict[str, Any], now: datetime) -> None:
        canonical_name = str(item.get("canonicalName") or item.get("canonical_name") or "").strip()
        if not canonical_name:
            raise _story_error(422, "CANON_SCHEMA_INVALID", "实体名称不能为空。")
        entity_type_id = str(item.get("entityTypeId") or item.get("entity_type_id") or "").strip()
        entity_type_name = str(item.get("entityTypeName") or item.get("entity_type_name") or "").strip()
        entity_type = session.get(CanonEntityType, entity_type_id) if entity_type_id else None
        if entity_type is None and entity_type_name:
            entity_type = session.scalar(select(CanonEntityType).where(CanonEntityType.name == entity_type_name))
        if entity_type is None:
            raise _story_error(422, "CANON_SCHEMA_INVALID", "实体类型不存在。")
        attributes = item.get("attributesJson") or item.get("attributes_json") or {}
        schema = _loads(entity_type.schema_json, {})
        if not _json_schema_subset_valid(schema, attributes):
            raise _story_error(422, "CANON_SCHEMA_INVALID", "实体属性不符合 Schema。")
        row = session.scalar(select(CanonEntity).where(CanonEntity.canonical_name == canonical_name))
        if row and row.status == "locked":
            raise _story_error(409, "CANON_LOCKED", "Canon 已锁定。")
        is_new = row is None
        if not row:
            row = CanonEntity(id=str(uuid4()), entity_type_id=entity_type.id, canonical_name=canonical_name, created_at=now, updated_at=now)
            session.add(row)
        row.aliases_json = _dumps([alias for alias in (item.get("aliasesJson") or item.get("aliases_json") or []) if isinstance(alias, str)])
        row.attributes_json = _dumps(attributes)
        row.status = "draft"
        if not is_new:
            row.revision += 1
        row.source_document_id = item.get("sourceDocumentId") or item.get("source_document_id")
        row.updated_at = now

    def _upsert_relation(self, session: Session, item: dict[str, Any], now: datetime) -> None:
        relation_id = str(item.get("id") or uuid4())
        row = session.get(CanonRelation, relation_id)
        if row and row.status == "locked":
            raise _story_error(409, "CANON_LOCKED", "Canon 已锁定。")
        is_new = row is None
        subject_entity_id = str(item.get("subjectEntityId") or item.get("subject_entity_id") or "").strip()
        subject_name = str(
            item.get("subjectCanonicalName")
            or item.get("subject_canonical_name")
            or item.get("subject")
            or ""
        ).strip()
        if not subject_entity_id and subject_name:
            subject = session.scalar(select(CanonEntity).where(CanonEntity.canonical_name == subject_name))
            subject_entity_id = subject.id if subject else ""
        predicate = str(item.get("predicate") or "").strip()
        object_entity_id = item.get("objectEntityId") or item.get("object_entity_id")
        object_name = str(
            item.get("objectCanonicalName")
            or item.get("object_canonical_name")
            or item.get("object")
            or ""
        ).strip()
        if not object_entity_id and object_name:
            object_entity = session.scalar(select(CanonEntity).where(CanonEntity.canonical_name == object_name))
            object_entity_id = object_entity.id if object_entity else None
        object_value = item["objectValueJson"] if "objectValueJson" in item else item.get("object_value_json")
        if not subject_entity_id or session.get(CanonEntity, subject_entity_id) is None:
            raise _story_error(422, "CANON_SCHEMA_INVALID", "关系的主语实体不存在。")
        if not predicate:
            raise _story_error(422, "CANON_SCHEMA_INVALID", "关系谓词不能为空。")
        if object_entity_id and session.get(CanonEntity, str(object_entity_id)) is None:
            raise _story_error(422, "CANON_SCHEMA_INVALID", "关系的宾语实体不存在。")
        if not object_entity_id and object_value is None:
            raise _story_error(422, "CANON_SCHEMA_INVALID", "关系必须包含宾语实体或宾语值。")
        if not row:
            row = CanonRelation(id=relation_id, created_at=now, updated_at=now)
            session.add(row)
        row.subject_entity_id = subject_entity_id
        row.predicate = predicate
        row.object_entity_id = str(object_entity_id) if object_entity_id else None
        row.object_value_json = _dumps(object_value) if object_value is not None else None
        row.status = "draft"
        if not is_new:
            row.revision += 1
        row.source_document_id = item.get("sourceDocumentId") or item.get("source_document_id")
        row.updated_at = now

    def _upsert_rule(self, session: Session, item: dict[str, Any], now: datetime) -> None:
        rule_code = str(item.get("ruleCode") or item.get("rule_code") or "").strip()
        if not rule_code:
            raise _story_error(422, "CANON_SCHEMA_INVALID", "规则编码不能为空。")
        row = session.scalar(select(CanonRule).where(CanonRule.rule_code == rule_code))
        if row and row.status == "locked":
            raise _story_error(409, "CANON_LOCKED", "Canon 已锁定。")
        is_new = row is None
        if not row:
            row = CanonRule(id=str(uuid4()), rule_code=rule_code, created_at=now, updated_at=now)
            session.add(row)
        row.category = str(item.get("category") or row.category or "general")
        row.statement = str(item.get("statement") or "")
        row.severity = str(item.get("severity") or row.severity or "medium")
        row.constraint_json = _dumps(item.get("constraintJson") or item.get("constraint_json") or {})
        row.status = "draft"
        if not is_new:
            row.revision += 1
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

    def _canon_target_snapshot(self, target: Any) -> dict[str, Any]:
        if isinstance(target, CanonDocument):
            return self._document_out(target).model_dump(mode="json", by_alias=True)
        if isinstance(target, CanonEntityType):
            return self._entity_type_out(target).model_dump(mode="json", by_alias=True)
        if isinstance(target, CanonEntity):
            return self._canon_entity_out(target).model_dump(mode="json", by_alias=True)
        if isinstance(target, CanonRelation):
            return self._relation_out(target).model_dump(mode="json", by_alias=True)
        if isinstance(target, CanonRule):
            return self._rule_out(target).model_dump(mode="json", by_alias=True)
        raise _story_error(422, "CANON_TARGET_NOT_FOUND", "不支持的 Canon 目标。")

    @staticmethod
    def _patch_value(payload: dict[str, Any], camel: str, snake: str, current: Any) -> Any:
        if camel in payload:
            return payload[camel]
        if snake in payload:
            return payload[snake]
        return current

    def _apply_canon_target_patch(self, session: Session, target: Any, payload: dict[str, Any]) -> None:
        if isinstance(target, CanonDocument):
            target.title = str(payload.get("title", target.title))
            target.kind = str(payload.get("kind", target.kind))
            target.content_markdown = str(self._patch_value(payload, "contentMarkdown", "content_markdown", target.content_markdown))
        elif isinstance(target, CanonEntityType):
            schema_json = self._patch_value(payload, "schemaJson", "schema_json", _loads(target.schema_json, {}))
            if not _canon_schema_is_safe(schema_json):
                raise _story_error(422, "CANON_SCHEMA_INVALID", "实体类型 Schema 不安全。")
            target.display_name = str(self._patch_value(payload, "displayName", "display_name", target.display_name))
            target.schema_json = _dumps(schema_json)
        elif isinstance(target, CanonEntity):
            target.aliases_json = _dumps(self._patch_value(payload, "aliasesJson", "aliases_json", _loads(target.aliases_json, [])))
            attrs = self._patch_value(payload, "attributesJson", "attributes_json", _loads(target.attributes_json, {}))
            entity_type = session.get(CanonEntityType, target.entity_type_id) if hasattr(target, "entity_type_id") else None
            if entity_type and not _json_schema_subset_valid(_loads(entity_type.schema_json, {}), attrs):
                raise _story_error(422, "CANON_SCHEMA_INVALID", "实体属性不符合 Schema。")
            target.attributes_json = _dumps(attrs)
        elif isinstance(target, CanonRelation):
            target.predicate = str(payload.get("predicate", target.predicate))
            object_value = self._patch_value(payload, "objectValueJson", "object_value_json", _loads(target.object_value_json, None))
            target.object_value_json = _dumps(object_value) if object_value is not None else None
        elif isinstance(target, CanonRule):
            target.statement = str(payload.get("statement", target.statement))
            target.severity = str(payload.get("severity", target.severity))
            target.constraint_json = _dumps(self._patch_value(payload, "constraintJson", "constraint_json", _loads(target.constraint_json, {})))
        else:
            raise _story_error(422, "CANON_TARGET_NOT_FOUND", "不支持的 Canon 目标。")

    def _validate_state_payload(self, session: Session, project_id: str, data: dict[str, Any]) -> None:
        if not isinstance(data, dict):
            raise _story_error(422, "STATE_PAYLOAD_INVALID", "状态候选必须是 JSON object。")
        for collection in ("entities", "facts", "events", "foreshadows", "boundaries"):
            if not isinstance(data.get(collection, []), list):
                raise _story_error(422, "STATE_PAYLOAD_INVALID", f"{collection} 必须是数组。")

        known_names = set(session.scalars(select(StoryEntity.canonical_name).where(
            StoryEntity.project_id == project_id,
            StoryEntity.status == "active",
        )).all())
        seen_names: set[str] = set()
        for index, item in enumerate(data.get("entities", [])):
            if not isinstance(item, dict):
                raise _story_error(422, "STATE_PAYLOAD_INVALID", f"entities[{index}] 必须是 object。")
            name = str(item.get("canonicalName") or item.get("canonical_name") or "").strip()
            type_id = str(item.get("entityTypeId") or item.get("entity_type_id") or "").strip()
            if not name or name in seen_names:
                raise _story_error(422, "STATE_PAYLOAD_INVALID", f"entities[{index}] 名称为空或重复。")
            entity_type = session.get(CanonEntityType, type_id) if type_id else None
            if entity_type is None:
                type_name = str(item.get("entityTypeName") or item.get("entity_type_name") or "").strip()
                if type_name:
                    entity_type = session.scalar(select(CanonEntityType).where(CanonEntityType.name == type_name))
            if not entity_type:
                raise _story_error(422, "STATE_PAYLOAD_INVALID", f"entities[{index}] 的实体类型不存在。")
            attributes = item.get("attributes") or {}
            if not isinstance(attributes, dict) or not _json_schema_subset_valid(_loads(entity_type.schema_json, {}), attributes):
                raise _story_error(422, "STATE_PAYLOAD_INVALID", f"entities[{index}] 的属性不符合 Canon Schema。")
            seen_names.add(name)
            known_names.add(name)

        for index, item in enumerate(data.get("facts", [])):
            if not isinstance(item, dict):
                raise _story_error(422, "STATE_PAYLOAD_INVALID", f"facts[{index}] 必须是 object。")
            name = str(item.get("entity") or item.get("entityName") or "").strip()
            field_path = str(item.get("fieldPath") or item.get("field_path") or "").strip()
            confidence = item.get("confidence", 1.0)
            if name not in known_names or not field_path:
                raise _story_error(422, "STATE_PAYLOAD_INVALID", f"facts[{index}] 引用了未知实体或空字段。")
            if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= float(confidence) <= 1:
                raise _story_error(422, "STATE_PAYLOAD_INVALID", f"facts[{index}] confidence 必须在 0 到 1 之间。")

        for index, item in enumerate(data.get("events", [])):
            if not isinstance(item, dict) or not str(item.get("summary") or "").strip():
                raise _story_error(422, "STATE_PAYLOAD_INVALID", f"events[{index}] 必须包含摘要。")
            try:
                int(item.get("eventOrder") or item.get("event_order") or 0)
            except (TypeError, ValueError) as exc:
                raise _story_error(422, "STATE_PAYLOAD_INVALID", f"events[{index}] 的顺序无效。") from exc

        allowed_foreshadow_status = {"pending", "planted", "progressing", "resolved"}
        seen_codes: set[str] = set()
        for index, item in enumerate(data.get("foreshadows", [])):
            if not isinstance(item, dict):
                raise _story_error(422, "STATE_PAYLOAD_INVALID", f"foreshadows[{index}] 必须是 object。")
            code = str(item.get("code") or "").strip()
            if code and code in seen_codes:
                raise _story_error(422, "STATE_PAYLOAD_INVALID", f"foreshadows[{index}] code 重复。")
            if code:
                seen_codes.add(code)
            status = str(item.get("status") or "pending")
            if status not in allowed_foreshadow_status:
                raise _story_error(422, "STATE_PAYLOAD_INVALID", f"foreshadows[{index}] 状态无效。")
            window = [item.get("earliestChapter") or item.get("earliest_chapter"), item.get("targetChapter") or item.get("target_chapter"), item.get("latestChapter") or item.get("latest_chapter")]
            present = [value for value in window if value is not None]
            if any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in present):
                raise _story_error(422, "STATE_PAYLOAD_INVALID", f"foreshadows[{index}] 章节窗口无效。")
            if present and present != sorted(present):
                raise _story_error(422, "STATE_PAYLOAD_INVALID", f"foreshadows[{index}] 章节窗口顺序无效。")

        for index, item in enumerate(data.get("boundaries", [])):
            if not isinstance(item, dict):
                raise _story_error(422, "STATE_PAYLOAD_INVALID", f"boundaries[{index}] 必须是 object。")
            name = str(item.get("entity") or item.get("entityName") or "").strip()
            if name not in known_names or not isinstance(item.get("knowledge", {}), dict):
                raise _story_error(422, "STATE_PAYLOAD_INVALID", f"boundaries[{index}] 引用了未知实体或知识结构无效。")

    def _materialize_state_payload(self, session: Session, project_id: str, data: dict[str, Any], source_version_id: str, now: datetime) -> None:
        entities_by_name: dict[str, StoryEntity] = {
            entity.canonical_name: entity
            for entity in session.scalars(select(StoryEntity).where(
                StoryEntity.project_id == project_id,
                StoryEntity.status == "active",
            )).all()
        }
        for entity_item in data.get("entities", []) if isinstance(data.get("entities"), list) else []:
            if not isinstance(entity_item, dict):
                continue
            canonical_name = str(entity_item.get("canonicalName") or entity_item.get("canonical_name") or "").strip()
            if not canonical_name:
                continue
            entity_type_id = str(entity_item.get("entityTypeId") or entity_item.get("entity_type_id") or "")
            if not entity_type_id:
                entity_type_name = str(entity_item.get("entityTypeName") or entity_item.get("entity_type_name") or "").strip()
                entity_type = session.scalar(select(CanonEntityType).where(CanonEntityType.name == entity_type_name))
                entity_type_id = entity_type.id if entity_type else ""
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
            is_new = row.source_version_id is None
            row.entity_type_id = entity_type_id
            row.aliases_json = _dumps([alias for alias in (entity_item.get("aliases") or []) if isinstance(alias, str)])
            row.attributes_json = _dumps(entity_item.get("attributes") or {})
            row.status = "active"
            if is_new:
                row.source_version_id = source_version_id
            else:
                row.revision += 1
            row.updated_at = now
            entities_by_name[canonical_name] = row

        for fact_item in data.get("facts", []) if isinstance(data.get("facts"), list) else []:
            if not isinstance(fact_item, dict):
                continue
            entity_name = str(fact_item.get("entity") or fact_item.get("entityName") or "").strip()
            field_path = str(fact_item.get("fieldPath") or fact_item.get("field_path") or "").strip()
            entity = entities_by_name[entity_name]
            current = session.scalars(select(StateFact).where(StateFact.project_id == project_id, StateFact.entity_id == entity.id, StateFact.field_path == field_path, StateFact.is_current.is_(True))).all()
            new_value = fact_item.get("value")
            if current and _loads(current[0].value_json, None) == new_value:
                continue
            if current:
                expected_present = "expectedCurrentValue" in fact_item or "expected_current_value" in fact_item
                expected_value = fact_item.get("expectedCurrentValue") if "expectedCurrentValue" in fact_item else fact_item.get("expected_current_value")
                if not expected_present or _loads(current[0].value_json, None) != expected_value:
                    raise _story_error(409, "STATE_FACT_CONFLICT", "状态事实与当前值冲突，未写入正式状态。", {
                        "entityId": entity.id,
                        "entityName": entity.canonical_name,
                        "fieldPath": field_path,
                        "currentValue": _loads(current[0].value_json, None),
                    })
            for existing in current:
                existing.is_current = False
                existing.valid_to = now
                existing.updated_at = now
            fact = StateFact(
                id=str(uuid4()),
                project_id=project_id,
                entity_id=entity.id,
                field_path=field_path,
                value_json=_dumps(new_value),
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
        session.execute(text("DELETE FROM retrieval_fts WHERE project_id = :project_id"), {"project_id": project_id})
        session.execute(text("DELETE FROM retrieval_index_entries WHERE project_id = :project_id"), {"project_id": project_id})
        entries: list[dict[str, Any]] = []
        for doc in session.scalars(select(CanonDocument).where(CanonDocument.kind == "story-core", CanonDocument.status == "locked")).all():
            entries.append({"kind": "canon_document", "title": doc.title, "content": doc.content_markdown, "source_version_id": None, "entity_id": None, "checksum": _stable_digest(doc.content_markdown), "source_status": "official"})
        for entity in session.scalars(select(StoryEntity).where(StoryEntity.project_id == project_id, StoryEntity.status == "active")).all():
            facts = session.scalars(select(StateFact).where(StateFact.project_id == project_id, StateFact.entity_id == entity.id, StateFact.is_current.is_(True))).all()
            content = " ".join([entity.canonical_name] + [f"{fact.field_path}:{_loads(fact.value_json, None)}" for fact in facts])
            latest_fact = max(facts, key=lambda item: item.valid_from or item.created_at, default=None)
            entries.append({"kind": "entity", "title": entity.canonical_name, "content": content, "source_version_id": latest_fact.source_version_id if latest_fact else entity.source_version_id, "entity_id": entity.id, "checksum": _stable_digest(content), "source_status": "official"})
        for event in session.scalars(
            select(StoryEvent).join(SourceVersion, SourceVersion.id == StoryEvent.source_version_id)
            .where(StoryEvent.project_id == project_id, SourceVersion.status == "official")
        ).all():
            entries.append({"kind": "event", "title": event.summary[:120] or event.location or event.id, "content": event.summary, "source_version_id": event.source_version_id, "entity_id": None, "checksum": _stable_digest(event.summary), "source_status": "official"})
        for foreshadow in session.scalars(
            select(Foreshadow).join(SourceVersion, SourceVersion.id == Foreshadow.source_version_id)
            .where(Foreshadow.project_id == project_id, Foreshadow.status != "superseded", SourceVersion.status == "official")
        ).all():
            entries.append({"kind": "foreshadow", "title": foreshadow.label, "content": foreshadow.description, "source_version_id": foreshadow.source_version_id, "entity_id": None, "checksum": _stable_digest(foreshadow.description), "source_status": "official"})

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
        vector_available = self.vector_backend.available
        if vector_available:
            try:
                self.vector_backend.rebuild(project_id, entries)
            except Exception as exc:  # vector data is a rebuildable projection
                vector_available = False
                session.add(self.service._audit(
                    "retrieval.vector_rebuild_failed",
                    "retrieval_index",
                    project_id,
                    {"backend": self.vector_backend.name, "errorType": type(exc).__name__},
                    str(uuid4()),
                ))
        state.last_rebuilt_at = now
        state.indexed_count = len(entries)
        state.vector_backend = self.vector_backend.name
        state.vector_available = vector_available
        state.checksum = _stable_digest(entries)
        state.updated_at = now

    def _exact_retrieval_hits(self, session: Session, project_id: str, query: str, limit: int) -> list[dict[str, Any]]:
        lowered = query.lower()
        hits: list[dict[str, Any]] = []
        for entity in session.scalars(select(StoryEntity).where(StoryEntity.project_id == project_id, StoryEntity.status == "active")).all():
            aliases = _loads(entity.aliases_json, [])
            if lowered in entity.canonical_name.lower() or any(lowered in str(alias).lower() for alias in aliases):
                current_source = session.scalar(
                    select(StateFact.source_version_id)
                    .join(SourceVersion, SourceVersion.id == StateFact.source_version_id)
                    .where(StateFact.entity_id == entity.id, StateFact.is_current.is_(True), SourceVersion.status == "official")
                    .order_by(StateFact.valid_from.desc())
                )
                hits.append(self._retrieval_hit({
                    "id": entity.id,
                    "kind": "entity",
                    "title": entity.canonical_name,
                    "content": _dumps(_loads(entity.attributes_json, {})),
                    "source_version_id": current_source or entity.source_version_id,
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
        state = session.get(RetrievalIndexState, project_id)
        if not self.vector_backend.available or (state is not None and not state.vector_available):
            return []
        rows = session.execute(text("SELECT entry_id, kind, title, content, source_version_id, entity_id, checksum, source_status FROM retrieval_index_entries WHERE project_id = :project_id"), {"project_id": project_id}).mappings().all()
        return [self._retrieval_hit(row) for row in self.vector_backend.search([dict(row) for row in rows], query, limit)]

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

    def _mirror_canon_markdown_safely(self, project_id: str, folder_path: str) -> None:
        """Treat Markdown as a recoverable projection, never as the authority.

        The database transaction has already committed when this runs. A file
        system failure is therefore diagnosed and can be repaired by a later
        rebuild instead of returning a misleading failed-write response.
        """
        try:
            self._mirror_canon_markdown_for_project(project_id, folder_path)
        except OSError as exc:
            with self.service.db.project_write(project_id, folder_path) as session:
                session.add(self.service._audit(
                    "canon.mirror_failed",
                    "canon_document",
                    "story-core",
                    {"errorType": type(exc).__name__, "rebuildRequired": True},
                    str(uuid4()),
                ))
