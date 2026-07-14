from __future__ import annotations

import asyncio
from collections import Counter
import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, AsyncIterator
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from .config import Settings
from .database import DatabaseManager
from .model_provider import ModelProviderError, OpenAICompatibleModelProvider
from .phase4 import Phase4Service
from .models import (
    AgentMessage,
    AgentSession,
    AuditEvent,
    CatalogProject,
    CanonChangeRequest,
    CanonDocument,
    CanonEntity,
    CanonEntityType,
    CanonRelation,
    CanonRule,
    ChangeOperation,
    ChangeProposal,
    ContextTrace,
    ModelConfig,
    ModelProvider,
    ModelRoleBinding,
    ModelRun,
    Plan,
    PlanNode,
    RetrievalIndexState,
    SourceVersion,
    ProjectMeta,
    StateDelta,
    StateFact,
    StateSnapshot,
    StoryEvent,
    ProposalImpact,
    StoryEntity,
    StoryMarker,
    Foreshadow,
    ExportArtifact,
    ExportJob,
    ExportJobChapter,
    KnowledgeBoundary,
    utc_now,
)
from .schemas import (
    AgentMessageCreate,
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
    ModelConfigCreate,
    ModelConfigUpdate,
    ModelProviderCreate,
    ModelProviderUpdate,
    ModelRoleBindingUpdate,
    PlanNodeCreate,
    RetrievalHit,
    RetrievalQuery,
    RetrievalStatus,
    SourceVersionOut,
    SourceVersionSupersede,
    PlanNodeUpdate,
    ProjectCreate,
    ProjectUpdate,
    StateCandidateCommit,
    StateCandidateCreate,
    StateDeltaOut,
    StateFactOut,
    StateSnapshotOut,
    StoryEntityOut,
    StoryEventOut,
    ProposalApply,
    ProposalReject,
)
from .secrets import SecretStore, SecretStoreUnavailable, default_secret_store, secret_preview


class StoryError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_json_default)


def loads(value: str) -> Any:
    return json.loads(value or "null")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower()
    return slug[:60] or "story"


def stable_digest(value: Any) -> str:
    return hashlib.sha256(dumps(value).encode("utf-8")).hexdigest()


def token_estimate(text_value: str) -> int:
    if not text_value:
        return 0
    return max(1, (len(text_value) + 3) // 4)


def safe_json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except ValueError:
        return default


def remap_json_identifier(value: Any, old_id: str, new_id: str) -> Any:
    if isinstance(value, str):
        return new_id if value == old_id else value
    if isinstance(value, list):
        return [remap_json_identifier(item, old_id, new_id) for item in value]
    if isinstance(value, dict):
        return {key: remap_json_identifier(item, old_id, new_id) for key, item in value.items()}
    return value


def json_schema_subset_valid(schema: Any, value: Any) -> bool:
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
        if isinstance(required, list):
            for name in required:
                if name not in value:
                    return False
        additional_properties = schema.get("additionalProperties", True)
        if additional_properties is False:
            allowed = set(properties)
            if any(key not in allowed for key in value):
                return False
        for key, prop_schema in properties.items():
            if key in value and not json_schema_subset_valid(prop_schema, value[key]):
                return False
        return True
    if schema_type == "array":
        if not isinstance(value, list):
            return False
        items = schema.get("items")
        return True if items is None else all(json_schema_subset_valid(items, item) for item in value)
    if schema_type == "string":
        if not isinstance(value, str):
            return False
        enum = schema.get("enum")
        return True if not enum else value in enum
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


def canon_schema_is_safe(schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    if schema.get("type") not in {"object", "array", "string", "integer", "number", "boolean", "null", None}:
        return False
    if "pattern" in schema or "format" in schema:
        return False
    for key in ("properties", "definitions", "$defs"):
        value = schema.get(key)
        if isinstance(value, dict) and any(not canon_schema_is_safe(item) for item in value.values()):
            return False
    items = schema.get("items")
    if items is not None and not canon_schema_is_safe(items):
        return False
    return True


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temp_path = Path(handle.name)
        handle.write(content)
    temp_path.replace(path)


MODEL_ROLES = [
    "architect",
    "planner",
    "chinese_writer",
    "fact_extractor",
    "logic_reviewer",
    "continuity_reviewer",
    "story_editor",
    "style_reviewer",
    "reviser",
    "embedding",
]

STRUCTURED_ACTIONS = {"replan", "logic_check", "complete_dependencies"}
PROPOSAL_FIELD_MAP = {
    "targetChapter": ("target_chapter", "目标章节", "integer"),
    "rangeMin": ("range_min", "允许范围起点", "integer"),
    "rangeMax": ("range_max", "允许范围终点", "integer"),
    "prerequisites": ("prerequisites_json", "前置条件", "list"),
    "completionConditions": ("completion_conditions_json", "完成条件", "list"),
    "foreshadows": ("foreshadows_json", "伏笔", "list"),
    "contracts": ("contracts_json", "章节契约", "list"),
    "note": ("note", "备注", "string"),
    "pace": ("pace", "节奏状态", "string"),
}
JSON_PROPOSAL_SCHEMA_HINT = {
    "targetId": "必须是当前规划里已存在的里程碑 id",
    "expectedRevision": "目标里程碑当前 revision",
    "reason": "为什么建议这些修改",
    "operations": [
        {
            "field": "targetChapter|rangeMin|rangeMax|prerequisites|completionConditions|foreshadows|contracts|note|pace",
            "after": "字段的新值；章节字段为整数，列表字段为字符串数组",
        }
    ],
    "impacts": [{"kind": "contract|foreshadow|dependency|pace|chapter_window", "label": "影响说明"}],
}


class CatalogProviderSnapshot:
    def __init__(self, provider: ModelProvider):
        self.id = provider.id
        self.name = provider.name
        self.base_url = provider.base_url
        self.timeout_seconds = provider.timeout_seconds
        self.max_retries = provider.max_retries
        self.is_enabled = provider.is_enabled
        self.api_key_ref = provider.api_key_ref


class CatalogModelSnapshot:
    def __init__(self, model: ModelConfig):
        self.id = model.id
        self.model_id = model.model_id
        self.display_name = model.display_name
        self.temperature = model.temperature
        self.max_output_tokens = model.max_output_tokens
        self.supports_reasoning = model.supports_reasoning
        self.is_enabled = model.is_enabled
        self.input_price_per_million = model.input_price_per_million
        self.output_price_per_million = model.output_price_per_million


class StoryService:
    def __init__(self, settings: Settings, secret_store: SecretStore | None = None):
        self.settings = settings
        self.db = DatabaseManager(settings)
        self.secret_store = secret_store or default_secret_store()
        self._cancelled_runs: set[str] = set()
        self.phase4 = Phase4Service(self)
        from .phase5 import Phase5Service
        from .phase7 import Phase7Service
        from .phase8 import Phase8Service
        from .phase9 import Phase9Service
        from .phase10 import Phase10Service

        self.phase5 = Phase5Service(self)
        self.phase7 = Phase7Service(self)
        self.phase8 = Phase8Service(self)
        self.phase9 = Phase9Service(self)
        self.phase10 = Phase10Service(self)

    def close(self) -> None:
        self.db.dispose()

    def initialize(self) -> None:
        self._ensure_model_role_bindings()
        if self.settings.seed_demo and not self.list_projects():
            self.create_project(ProjectCreate(title="夜巡人·演示（从第36章开始）", mode="long-form", total_chapters=1000), seed_demo=True)
        self._recover_interrupted_model_runs()
        self.phase4.ensure_existing_projects()
        self.phase8.recover_interrupted_generations()
        self.phase5.recover_interrupted_jobs()
        self.phase7.recover_interrupted_automation()
        self.phase9.recover_interrupted_exports()
        self.phase10.recover_interrupted_endurance()

    def _ensure_model_role_bindings(self) -> None:
        now = utc_now()
        with self.db.catalog() as session:
            existing = set(session.scalars(select(ModelRoleBinding.role)).all())
            for role in MODEL_ROLES:
                if role not in existing:
                    session.add(ModelRoleBinding(role=role, model_id=None, created_at=now, updated_at=now))
            session.commit()

    def _recover_interrupted_model_runs(self) -> None:
        now = utc_now()
        for project in self.list_projects():
            with self.db.project_write(project.id, project.folder_path) as session:
                runs = session.scalars(select(ModelRun).where(ModelRun.status.in_(["running", "cancel_requested"]))).all()
                for run in runs:
                    if run.status == "cancel_requested":
                        run.status = "cancelled"
                        run.error_code = "startup_recovery_cancelled"
                    else:
                        run.status = "interrupted"
                        run.error_code = "startup_recovery"
                    run.ended_at = now
                sessions = session.scalars(select(AgentSession).where(AgentSession.status == "thinking")).all()
                for agent_session in sessions:
                    agent_session.status = "error"
                    agent_session.updated_at = now

    def list_projects(self) -> list[CatalogProject]:
        with self.db.catalog() as session:
            return list(session.scalars(select(CatalogProject).order_by(CatalogProject.last_opened_at.desc())).all())

    def list_model_providers(self) -> list[dict[str, Any]]:
        with self.db.catalog() as session:
            providers = session.scalars(select(ModelProvider).order_by(ModelProvider.created_at.desc())).all()
            return [self._provider_dict(item) for item in providers]

    def create_model_provider(self, payload: ModelProviderCreate) -> dict[str, Any]:
        self._validate_base_url(payload.base_url)
        now = utc_now()
        provider_id = str(uuid4())
        key_ref = f"model-provider:{provider_id}"
        provider = ModelProvider(
            id=provider_id,
            name=payload.name,
            provider_type=payload.provider_type,
            base_url=payload.base_url.rstrip("/"),
            timeout_seconds=payload.timeout_seconds,
            max_retries=payload.max_retries,
            is_enabled=payload.is_enabled,
            created_at=now,
            updated_at=now,
        )
        if payload.api_key:
            self._store_provider_secret(provider, key_ref, payload.api_key)
        with self.db.catalog() as session:
            session.add(provider)
            session.commit()
            session.refresh(provider)
            return self._provider_dict(provider)

    def get_model_provider(self, provider_id: str) -> dict[str, Any]:
        with self.db.catalog() as session:
            provider = session.get(ModelProvider, provider_id)
            if not provider:
                raise StoryError(404, "MODEL_PROVIDER_NOT_FOUND", "模型供应商不存在。", {"providerId": provider_id})
            return self._provider_dict(provider)

    def update_model_provider(self, provider_id: str, payload: ModelProviderUpdate) -> dict[str, Any]:
        with self.db.catalog() as session:
            provider = session.get(ModelProvider, provider_id)
            if not provider:
                raise StoryError(404, "MODEL_PROVIDER_NOT_FOUND", "模型供应商不存在。", {"providerId": provider_id})
            changes = payload.model_dump(exclude_unset=True, exclude={"api_key", "clear_api_key"})
            if "base_url" in changes:
                self._validate_base_url(changes["base_url"])
                changes["base_url"] = changes["base_url"].rstrip("/")
            for key, value in changes.items():
                setattr(provider, key, value)
            if payload.clear_api_key and provider.api_key_ref:
                self._delete_provider_secret(provider.api_key_ref)
                provider.api_key_ref = None
                provider.api_key_preview = None
            if payload.api_key:
                key_ref = provider.api_key_ref or f"model-provider:{provider.id}"
                self._store_provider_secret(provider, key_ref, payload.api_key)
            if changes or payload.clear_api_key or payload.api_key:
                provider.last_test_status = None
                provider.last_tested_at = None
            provider.updated_at = utc_now()
            session.commit()
            session.refresh(provider)
            return self._provider_dict(provider)

    def delete_model_provider(self, provider_id: str) -> None:
        with self.db.catalog() as session:
            provider = session.get(ModelProvider, provider_id)
            if not provider:
                raise StoryError(404, "MODEL_PROVIDER_NOT_FOUND", "模型供应商不存在。", {"providerId": provider_id})
            model_count = len(session.scalars(select(ModelConfig.id).where(ModelConfig.provider_id == provider_id)).all())
            if model_count:
                raise StoryError(409, "MODEL_PROVIDER_IN_USE", "模型供应商仍被模型配置引用，不能删除。", {"modelCount": model_count})
            key_ref = provider.api_key_ref
            if key_ref:
                self._delete_provider_secret(key_ref)
            session.delete(provider)
            session.commit()

    def create_deepseek_preset(self) -> dict[str, Any]:
        with self.db.catalog() as session:
            existing = session.scalar(select(ModelProvider).where(
                ModelProvider.name == "DeepSeek 官方",
                ModelProvider.base_url == "https://api.deepseek.com",
            ))
            if existing:
                current_model = session.scalar(select(ModelConfig).where(
                    ModelConfig.provider_id == existing.id,
                    ModelConfig.model_id == "deepseek-v4-pro",
                ))
                existing_id = existing.id
                if current_model:
                    changed = False
                    if current_model.input_price_per_million is None:
                        current_model.input_price_per_million = 0.435
                        changed = True
                    if current_model.output_price_per_million is None:
                        current_model.output_price_per_million = 0.87
                        changed = True
                    if changed:
                        current_model.updated_at = utc_now()
                        session.commit()
                    return self._provider_dict(existing)
            else:
                existing_id = None
        if existing_id:
            self.create_model_config(existing_id, ModelConfigCreate(
                model_id="deepseek-v4-pro",
                display_name="DeepSeek V4 Pro",
                temperature=0.7,
                max_output_tokens=4096,
                supports_reasoning=True,
                is_enabled=True,
                input_price_per_million=0.435,
                output_price_per_million=0.87,
            ))
            return self.get_model_provider(existing_id)
        payload = ModelProviderCreate(name="DeepSeek 官方", base_url="https://api.deepseek.com", timeout_seconds=60, max_retries=1)
        provider = self.create_model_provider(payload)
        self.create_model_config(provider["id"], ModelConfigCreate(
            model_id="deepseek-v4-pro",
            display_name="DeepSeek V4 Pro",
            temperature=0.7,
            max_output_tokens=4096,
            supports_reasoning=True,
            is_enabled=True,
            input_price_per_million=0.435,
            output_price_per_million=0.87,
        ))
        return self.get_model_provider(provider["id"])

    def list_model_configs(self, provider_id: str) -> list[dict[str, Any]]:
        with self.db.catalog() as session:
            provider = session.get(ModelProvider, provider_id)
            if not provider:
                raise StoryError(404, "MODEL_PROVIDER_NOT_FOUND", "模型供应商不存在。", {"providerId": provider_id})
            models = session.scalars(select(ModelConfig).where(ModelConfig.provider_id == provider_id).options(selectinload(ModelConfig.provider)).order_by(ModelConfig.created_at.desc())).all()
            return [self._model_dict(item) for item in models]

    def create_model_config(self, provider_id: str, payload: ModelConfigCreate) -> dict[str, Any]:
        with self.db.catalog() as session:
            provider = session.get(ModelProvider, provider_id)
            if not provider:
                raise StoryError(404, "MODEL_PROVIDER_NOT_FOUND", "模型供应商不存在。", {"providerId": provider_id})
            now = utc_now()
            model = ModelConfig(
                id=str(uuid4()),
                provider_id=provider_id,
                model_id=payload.model_id,
                display_name=payload.display_name,
                temperature=payload.temperature,
                max_output_tokens=payload.max_output_tokens,
                supports_reasoning=payload.supports_reasoning,
                is_enabled=payload.is_enabled,
                input_price_per_million=payload.input_price_per_million,
                output_price_per_million=payload.output_price_per_million,
                created_at=now,
                updated_at=now,
            )
            session.add(model)
            session.commit()
            model.provider = provider
            return self._model_dict(model)

    def update_model_config(self, model_id: str, payload: ModelConfigUpdate) -> dict[str, Any]:
        with self.db.catalog() as session:
            model = session.scalar(select(ModelConfig).where(ModelConfig.id == model_id).options(selectinload(ModelConfig.provider)))
            if not model:
                raise StoryError(404, "MODEL_CONFIG_NOT_FOUND", "模型配置不存在。", {"modelId": model_id})
            for key, value in payload.model_dump(exclude_unset=True).items():
                setattr(model, key, value)
            model.updated_at = utc_now()
            session.commit()
            session.refresh(model)
            return self._model_dict(model)

    def delete_model_config(self, model_id: str) -> None:
        with self.db.catalog() as session:
            model = session.get(ModelConfig, model_id)
            if not model:
                raise StoryError(404, "MODEL_CONFIG_NOT_FOUND", "模型配置不存在。", {"modelId": model_id})
            bindings = session.scalars(select(ModelRoleBinding.role).where(ModelRoleBinding.model_id == model_id)).all()
            if bindings:
                raise StoryError(409, "MODEL_CONFIG_IN_USE", "模型仍被角色绑定引用，不能删除。", {"roles": bindings})
            session.delete(model)
            session.commit()

    def list_model_role_bindings(self) -> list[dict[str, Any]]:
        self._ensure_model_role_bindings()
        with self.db.catalog() as session:
            bindings = session.scalars(select(ModelRoleBinding).options(selectinload(ModelRoleBinding.model).selectinload(ModelConfig.provider)).order_by(ModelRoleBinding.role)).all()
            return [self._role_binding_dict(item) for item in bindings]

    def update_model_role_binding(self, role: str, payload: ModelRoleBindingUpdate) -> dict[str, Any]:
        if role not in MODEL_ROLES:
            raise StoryError(404, "MODEL_ROLE_NOT_FOUND", "模型角色不存在。", {"role": role})
        with self.db.catalog() as session:
            binding = session.get(ModelRoleBinding, role)
            if not binding:
                binding = ModelRoleBinding(role=role, created_at=utc_now())
                session.add(binding)
            if payload.model_id:
                model = session.get(ModelConfig, payload.model_id)
                if not model:
                    raise StoryError(404, "MODEL_CONFIG_NOT_FOUND", "模型配置不存在。", {"modelId": payload.model_id})
                binding.model_id = payload.model_id
            else:
                binding.model_id = None
            binding.daily_cost_limit = payload.daily_cost_limit
            binding.updated_at = utc_now()
            session.commit()
            binding = session.scalar(select(ModelRoleBinding).where(ModelRoleBinding.role == role).options(selectinload(ModelRoleBinding.model).selectinload(ModelConfig.provider)))
            assert binding
            return self._role_binding_dict(binding)

    def test_model_provider(self, provider_id: str) -> dict[str, Any]:
        with self.db.catalog() as session:
            provider = session.get(ModelProvider, provider_id)
            if not provider:
                raise StoryError(404, "MODEL_PROVIDER_NOT_FOUND", "模型供应商不存在。", {"providerId": provider_id})
            provider_data = self._provider_dict(provider)
            key_ref = provider.api_key_ref
            base_url = provider.base_url.rstrip("/")
            timeout_seconds = min(max(provider.timeout_seconds, 1), 5)

        def finish(ok: bool, status: str, model: str | None, message: str) -> dict[str, Any]:
            with self.db.catalog() as session:
                current = session.get(ModelProvider, provider_id)
                if current:
                    current.last_test_status = status
                    current.last_tested_at = utc_now()
                    session.commit()
            return self._connection_result(provider_data, ok, status, model, message)

        if not key_ref:
            return finish(False, "missing_api_key", None, "尚未保存 API Key。")
        try:
            api_key = self.secret_store.get_secret(key_ref)
        except SecretStoreUnavailable:
            return finish(False, "credential_unavailable", None, "Credential Manager 不可用。")
        if not api_key:
            return finish(False, "missing_api_key", None, "Credential Manager 中未找到密钥。")
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.get(f"{base_url}/models", headers={"Authorization": f"Bearer {api_key}"})
        except httpx.TimeoutException:
            return finish(False, "timeout", None, "连接测试超时。")
        except httpx.RequestError:
            return finish(False, "network_error", None, "无法连接模型服务。")
        if response.status_code in {401, 403}:
            return finish(False, "auth_failed", None, "模型服务拒绝鉴权。")
        if response.status_code >= 400:
            return finish(False, "network_error", None, f"模型服务返回 HTTP {response.status_code}。")
        try:
            data = response.json()
        except ValueError:
            return finish(False, "invalid_response", None, "模型服务返回了非 JSON 响应。")
        models = data.get("data") if isinstance(data, dict) else None
        actual_model = None
        if isinstance(models, list) and models:
            first = models[0]
            actual_model = first.get("id") if isinstance(first, dict) else str(first)
        return finish(True, "success", actual_model, "连接测试成功。")

    def get_project(self, project_id: str, *, touch: bool = False) -> CatalogProject:
        with self.db.catalog() as session:
            project = session.get(CatalogProject, project_id)
            if not project:
                raise StoryError(404, "PROJECT_NOT_FOUND", "作品不存在。", {"projectId": project_id})
            if touch:
                project.last_opened_at = utc_now()
                session.commit()
                session.refresh(project)
            return project

    def create_project(self, payload: ProjectCreate, *, seed_demo: bool = False) -> CatalogProject:
        project_id = str(uuid4())
        folder = (self.settings.projects_dir / f"{project_id}-{slugify(payload.title)}").resolve()
        if self.settings.projects_dir.resolve() not in folder.parents:
            raise StoryError(400, "INVALID_PROJECT_PATH", "作品目录超出允许的数据根目录。")
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "canon").mkdir()
        (folder / "backups").mkdir()
        (folder / "exports").mkdir()

        now = utc_now()
        catalog = CatalogProject(
            id=project_id,
            title=payload.title,
            slug=slugify(payload.title),
            mode=payload.mode,
            folder_path=str(folder),
            current_chapter=36 if seed_demo else 0,
            total_chapters=payload.total_chapters,
            project_kind="demo" if seed_demo else "standard",
            created_at=now,
            updated_at=now,
            last_opened_at=now,
        )
        try:
            with self.db.catalog() as session:
                session.add(catalog)
                session.commit()
            self.db.ensure_project_database(project_id, folder)
            self._seed_project_database(catalog, seed_demo=seed_demo)
            self.phase4.ensure_project_defaults(catalog.id, catalog.folder_path, catalog.title)
            self._write_project_files(catalog)
        except Exception:
            with self.db.catalog() as session:
                existing = session.get(CatalogProject, project_id)
                if existing:
                    session.delete(existing)
                    session.commit()
            try:
                (folder / ".failed-create").write_text("Project creation failed before commit completed.\n", encoding="utf-8")
            except OSError:
                pass
            raise
        return catalog

    def update_project(self, project_id: str, payload: ProjectUpdate) -> CatalogProject:
        project = self.get_project(project_id)
        changes = payload.model_dump(exclude_none=True)
        with self.db.catalog() as session:
            row = session.get(CatalogProject, project_id)
            assert row
            for key, value in changes.items():
                setattr(row, key, value)
            row.updated_at = utc_now()
            session.commit()
            session.refresh(row)
            project = row
        with self.db.project_write(project_id, project.folder_path) as session:
            meta = session.get(ProjectMeta, project_id)
            if meta:
                for key, value in changes.items():
                    setattr(meta, key, value)
                meta.updated_at = utc_now()
        self._write_project_files(project)
        return project

    def _write_project_files(self, project: CatalogProject) -> None:
        folder = Path(project.folder_path)
        project_json = {
            "id": project.id,
            "title": project.title,
            "mode": project.mode,
            "currentChapter": project.current_chapter,
            "totalChapters": project.total_chapters,
            "projectKind": project.project_kind,
            "schemaVersion": project.schema_version,
        }
        (folder / "project.json").write_text(json.dumps(project_json, ensure_ascii=False, indent=2), encoding="utf-8")
        canon = folder / "canon" / "story-core.md"
        if not canon.exists():
            canon.write_text(
                f"# {project.title} · Story Core\n\n> 状态：等待 Canon 分析器生成。本文件属于作者可读的权威目录。\n",
                encoding="utf-8",
            )

    def _seed_project_database(self, project: CatalogProject, *, seed_demo: bool) -> None:
        plan_id = str(uuid4())
        session_id = str(uuid4())
        with self.db.project_write(project.id, project.folder_path) as session:
            session.add(ProjectMeta(
                id=project.id, title=project.title, mode=project.mode,
                current_chapter=project.current_chapter, total_chapters=project.total_chapters,
                project_kind=project.project_kind,
            ))
            session.add(Plan(
                id=plan_id,
                book_title="全书",
                volume_title="第一卷：雾城夜巡" if seed_demo else "第一卷",
                arc_title="弧线 01：旧宅来信" if seed_demo else "故事弧 01",
                chapter_start=1,
                chapter_end=min(project.total_chapters, 100),
            ))
            nodes = self._demo_nodes(plan_id) if seed_demo else [
                PlanNode(
                    id="milestone-opening", plan_id=plan_id, title="故事开端", type="事件",
                    target_chapter=1, range_min=1, range_max=min(5, project.total_chapters), importance=3,
                    note="定义故事的第一个可验证里程碑。", prerequisites_json=dumps(["作品已创建"]),
                    completion_conditions_json=dumps(["主角进入初始情境"]), foreshadows_json="[]",
                    contracts_json=dumps(["契约 A01"]), pace="smooth",
                )
            ]
            session.add_all(nodes)
            if seed_demo:
                session.add_all(self._demo_markers(plan_id))
            agent_session = AgentSession(
                id=session_id, project_id=project.id,
                scope_json=dumps(["第一卷", "弧线 01", "首次直面纸人"]), status="idle",
            )
            session.add(agent_session)
            if seed_demo:
                session.add_all([
                    AgentMessage(id=str(uuid4()), session_id=session_id, role="user", content="我觉得‘首次直面纸人’发生得太早了，主角还没建立足够的好奇心与紧张感。"),
                    AgentMessage(id=str(uuid4()), session_id=session_id, role="assistant", content="我检查了第一卷节奏和前置契约。建议把该里程碑放到第二幕中段，并同步延长调查铺垫。"),
                ])
                session.add(self._make_proposal(nodes[1]))

    def _demo_nodes(self, plan_id: str) -> list[PlanNode]:
        raw = [
            ("milestone-letter", "收到旧宅来信", "事件", 8, 6, 10, 3, "主角收到一封没有署名的旧宅来信。", ["建立夜巡人的日常秩序"], ["主角决定前往旧宅"], ["来信上的潮湿指印"], ["契约 A01"], "smooth"),
            ("milestone-paper-man", "首次直面纸人", "关键事件", 18, 16, 21, 4, "主角首次与纸人近距离接触，恐惧与好奇并存。", ["已触发事件：收到旧宅来信（章 8）", "伏笔生效：纸人握功（章 15）"], ["主角确认纸人具备感知与记忆", "获得旧宅相关的新线索"], ["纸人的规则", "日记中的名字", "遗夜路线图"], ["契约 A02", "契约 C03", "伏笔 P02"], "fast"),
            ("milestone-clue", "纸人之谜揭开一角", "转折点", 45, 43, 48, 4, "纸人并非纯粹敌人。", ["完成纸人首次接触"], ["揭示纸人的部分行动规则"], ["血字契约"], ["契约 A02", "伏笔 P03"], "slow"),
            ("milestone-watch-office", "夜巡司介入", "事件", 70, 68, 72, 3, "夜巡司正式介入旧宅事件。", ["纸人线索形成闭环"], ["确立夜巡司的公开立场"], ["旧宅档案缺页"], ["契约 B01"], "fast"),
            ("milestone-truth", "旧宅真相浮出", "高潮点", 96, 92, 98, 5, "第一卷主谜面揭晓。", ["夜巡司介入", "纸人规则已确认"], ["回收第一卷主要伏笔", "建立第二卷主冲突"], ["雾城地下旧路"], ["契约 C03", "伏笔 P04"], "smooth"),
        ]
        return [PlanNode(
            id=item[0], plan_id=plan_id, title=item[1], type=item[2], target_chapter=item[3], range_min=item[4], range_max=item[5],
            importance=item[6], note=item[7], prerequisites_json=dumps(item[8]), completion_conditions_json=dumps(item[9]),
            foreshadows_json=dumps(item[10]), contracts_json=dumps(item[11]), pace=item[12],
        ) for item in raw]

    def _demo_markers(self, plan_id: str) -> list[StoryMarker]:
        raw = [("hook-1", "hook", 8, "来信钩子"), ("hook-2", "hook", 18, "纸人现身"), ("foreshadow-1", "foreshadow", 31, "纸人规则"), ("hook-3", "hook", 54, "档案缺页"), ("foreshadow-2", "foreshadow", 64, "夜巡司暗线"), ("hook-4", "hook", 86, "旧路入口")]
        return [StoryMarker(id=item[0], plan_id=plan_id, kind=item[1], chapter=item[2], label=item[3]) for item in raw]

    def _make_proposal(self, node: PlanNode) -> ChangeProposal:
        proposal_id = str(uuid4())
        proposal = ChangeProposal(
            id=proposal_id, target_id=node.id, target_title=node.title,
            reason="延长旧宅调查阶段，让主角的好奇与恐惧先形成张力，再进入正面对抗。",
        )
        proposal.operations = [
            ChangeOperation(id=str(uuid4()), proposal_id=proposal_id, field="targetChapter", label="目标章节", before_value=node.target_chapter, after_value=22, selected=True),
            ChangeOperation(id=str(uuid4()), proposal_id=proposal_id, field="rangeMin", label="允许范围起点", before_value=node.range_min, after_value=20, selected=True),
            ChangeOperation(id=str(uuid4()), proposal_id=proposal_id, field="rangeMax", label="允许范围终点", before_value=node.range_max, after_value=25, selected=True),
        ]
        proposal.impacts = [
            ProposalImpact(id=str(uuid4()), proposal_id=proposal_id, kind="contract", label="3 个章节契约"),
            ProposalImpact(id=str(uuid4()), proposal_id=proposal_id, kind="foreshadow", label="1 条伏笔"),
            ProposalImpact(id=str(uuid4()), proposal_id=proposal_id, kind="dependency", label="2 个前置依赖"),
        ]
        return proposal

    def get_plan(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id, touch=True)
        with self.db.project(project_id, project.folder_path) as session:
            plan = session.scalar(select(Plan).options(selectinload(Plan.nodes), selectinload(Plan.markers)))
            if not plan:
                raise StoryError(404, "PLAN_NOT_FOUND", "作品规划不存在。")
            return self._plan_dict(plan)

    def update_plan_node(self, project_id: str, node_id: str, payload: PlanNodeUpdate, request_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        with self.db.project_write(project_id, project.folder_path) as session:
            node = session.get(PlanNode, node_id)
            if not node:
                raise StoryError(404, "PLAN_NODE_NOT_FOUND", "规划节点不存在。")
            if node.revision != payload.expected_revision:
                raise StoryError(409, "REVISION_CONFLICT", "规划已被其他操作修改。", {"expectedRevision": payload.expected_revision, "currentRevision": node.revision})
            before = self._node_dict(node)
            changes = payload.model_dump(exclude_none=True, exclude={"expected_revision"})
            json_fields = {
                "prerequisites": "prerequisites_json",
                "completion_conditions": "completion_conditions_json",
                "foreshadows": "foreshadows_json",
                "contracts": "contracts_json",
                "chapter_beats": "chapter_beats_json",
            }
            for key, value in changes.items():
                if key == "chapter_beats":
                    value = [beat.model_dump(by_alias=True) for beat in (payload.chapter_beats or [])]
                setattr(node, json_fields.get(key, key), dumps(value) if key in json_fields else value)
            self._validate_node(node)
            node.revision += 1
            session.add(self._audit("plan_node.updated", "plan_node", node.id, {"before": before, "after": self._node_dict(node), "reversible": True}, request_id))
            session.flush()
            return self._node_dict(node)

    def create_plan_node(self, project_id: str, payload: PlanNodeCreate, request_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        with self.db.project_write(project_id, project.folder_path) as session:
            plan = session.scalar(select(Plan))
            if not plan:
                raise StoryError(404, "PLAN_NOT_FOUND", "作品规划不存在。")
            node = PlanNode(
                id=str(uuid4()),
                plan_id=plan.id,
                title=payload.title,
                type=payload.type,
                target_chapter=payload.target_chapter,
                range_min=payload.range_min,
                range_max=payload.range_max,
                importance=payload.importance,
                note=payload.note,
                prerequisites_json=dumps(payload.prerequisites),
                completion_conditions_json=dumps(payload.completion_conditions),
                foreshadows_json=dumps(payload.foreshadows),
                contracts_json=dumps(payload.contracts),
                chapter_beats_json=dumps([beat.model_dump(by_alias=True) for beat in payload.chapter_beats]),
                pace=payload.pace,
                revision=1,
            )
            self._validate_node(node)
            session.add(node)
            session.add(self._audit("plan_node.created", "plan_node", node.id, {
                "after": self._node_dict(node),
                "reversible": False,
            }, request_id))
            session.flush()
            return self._node_dict(node)

    def list_sessions(self, project_id: str) -> list[dict[str, Any]]:
        project = self.get_project(project_id)
        with self.db.project(project_id, project.folder_path) as session:
            sessions = session.scalars(select(AgentSession).options(selectinload(AgentSession.messages), selectinload(AgentSession.model_runs)).order_by(AgentSession.updated_at.desc())).all()
            return [self._session_dict(item) for item in sessions]

    def create_session(self, project_id: str, scope: list[str]) -> dict[str, Any]:
        project = self.get_project(project_id)
        with self.db.project_write(project_id, project.folder_path) as session:
            item = AgentSession(id=str(uuid4()), project_id=project_id, scope_json=dumps(scope), status="idle")
            session.add(item)
            session.flush()
            item.model_runs = []
            return self._session_dict(item)

    def send_message(self, session_id: str, payload: AgentMessageCreate) -> dict[str, Any]:
        project = self.get_project(payload.project_id)
        with self.db.project_write(project.id, project.folder_path) as session:
            agent_session = session.get(AgentSession, session_id)
            if not agent_session:
                raise StoryError(404, "AGENT_SESSION_NOT_FOUND", "Agent 会话不存在。")
            user_message = AgentMessage(id=str(uuid4()), session_id=session_id, role="user", content=payload.content)
            session.add(user_message)
            node = session.get(PlanNode, payload.selected_node_id) if payload.selected_node_id else None
            requests_change = bool(re.search(r"调整|重排|修改|节奏|提前|推后|逻辑", payload.content))
            if requests_change and node:
                content = f"我已重新检查“{node.title}”的章节窗口、前置条件和伏笔依赖。建议采用修改提案，确认后才会写入规划。"
                proposal = self._make_proposal(node)
                session.add(proposal)
            else:
                title = node.title if node else "当前规划"
                content = f"我已读取当前作用域。关于“{title}”，你可以继续说明希望强化的冲突或情绪。"
                proposal = None
            assistant = AgentMessage(id=str(uuid4()), session_id=session_id, role="assistant", content=content)
            session.add(assistant)
            agent_session.updated_at = utc_now()
            session.flush()
            return {"message": self._message_dict(assistant), "proposal": self._proposal_dict(proposal) if proposal else None}

    async def stream_agent_message(self, session_id: str, payload: AgentMessageCreate, request_id: str) -> AsyncIterator[dict[str, Any]]:
        project = self.get_project(payload.project_id)
        run_id = str(uuid4())
        started = time.perf_counter()
        role = "planner"
        compiled = self._prepare_model_call(project.id, project.folder_path, session_id, payload, role, run_id, request_id)
        provider = OpenAICompatibleModelProvider(
            base_url=compiled["baseUrl"],
            api_key=compiled["apiKey"],
            timeout_seconds=compiled["timeoutSeconds"],
            max_retries=compiled["maxRetries"],
        )
        status = "succeeded"
        error_code: str | None = None
        assistant_text = ""
        natural_run_completed = False
        try:
            yield {"event": "run_started", "runId": run_id, "provider": compiled["providerName"], "model": compiled["modelId"], "requestId": request_id}
            async for delta in provider.stream_chat(compiled["payload"]):
                if run_id in self._cancelled_runs:
                    status = "cancelled"
                    error_code = "cancelled"
                    yield {"event": "cancelled", "runId": run_id, "message": "模型调用已停止。"}
                    break
                assistant_text += delta
                yield {"event": "text_delta", "runId": run_id, "delta": delta}
            # Cancellation can arrive after the provider's final delta but
            # before the success transaction begins.
            if status == "succeeded" and run_id in self._cancelled_runs:
                status = "cancelled"
                error_code = "cancelled"
                yield {"event": "cancelled", "runId": run_id, "message": "模型调用已停止。"}
            if status == "succeeded":
                if not assistant_text.strip():
                    status = "failed"
                    error_code = "empty_response"
                    yield {"event": "failed", "runId": run_id, "errorCode": error_code, "message": "模型没有返回内容。"}
                else:
                    message = self._complete_model_run_success(project.id, project.folder_path, session_id, run_id, assistant_text, provider.last_result, started)
                    natural_run_completed = True
                    yield {"event": "completed", "runId": run_id, "message": message, "usage": {
                        "promptTokens": provider.last_result.prompt_tokens,
                        "completionTokens": provider.last_result.completion_tokens,
                        "totalTokens": provider.last_result.total_tokens,
                    }}
                    if payload.action in STRUCTURED_ACTIONS:
                        proposal_stream = self._stream_structured_proposal(project.id, project.folder_path, session_id, payload, request_id)
                        try:
                            async for proposal_event in proposal_stream:
                                yield proposal_event
                        except StoryError as exc:
                            yield {"event": "proposal_failed", "runId": None, "errorCode": exc.code, "message": exc.message, "attempts": 0}
                        except ModelProviderError as exc:
                            yield {"event": "proposal_failed", "runId": None, "errorCode": exc.code, "message": exc.message, "attempts": 0}
                        finally:
                            await proposal_stream.aclose()
                    return
        except ModelProviderError as exc:
            status = "failed"
            error_code = exc.code
            yield {"event": "failed", "runId": run_id, "errorCode": exc.code, "message": exc.message}
        except Exception:
            status = "failed"
            error_code = "internal_error"
            yield {"event": "failed", "runId": run_id, "errorCode": error_code, "message": "模型调用发生内部错误。"}
        except (asyncio.CancelledError, GeneratorExit):
            if not natural_run_completed:
                status = "cancelled"
                error_code = "client_disconnected"
                self._cancelled_runs.add(run_id)
            raise
        finally:
            if status != "succeeded" and not natural_run_completed:
                self._complete_model_run_failure(project.id, project.folder_path, session_id, run_id, status, error_code or status, started, retry_count=provider.last_result.retry_count)
            self._cancelled_runs.discard(run_id)

    def cancel_model_run(self, project_id: str, run_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        self._cancelled_runs.add(run_id)
        with self.db.project_write(project.id, project.folder_path) as session:
            run = session.get(ModelRun, run_id)
            if not run:
                raise StoryError(404, "MODEL_RUN_NOT_FOUND", "模型调用记录不存在。", {"runId": run_id})
            if run.status in {"running", "cancel_requested"}:
                run.status = "cancel_requested"
                run.error_code = "cancel_requested"
                run.ended_at = utc_now()
            agent_session = session.get(AgentSession, run.session_id) if run.session_id else None
            if agent_session and agent_session.status == "thinking":
                agent_session.status = "idle"
                agent_session.updated_at = utc_now()
            session.flush()
            return self._model_run_dict(run)

    def list_model_runs(self, project_id: str, limit: int = 100, status: str | None = None, role: str | None = None) -> list[dict[str, Any]]:
        project = self.get_project(project_id)
        with self.db.project(project.id, project.folder_path) as session:
            query = select(ModelRun).order_by(ModelRun.started_at.desc()).limit(min(limit, 500))
            if status:
                query = query.where(ModelRun.status == status)
            if role:
                query = query.where(ModelRun.role == role)
            return [self._model_run_dict(item) for item in session.scalars(query).all()]

    def list_proposals(self, project_id: str, status: str | None = None) -> list[dict[str, Any]]:
        project = self.get_project(project_id)
        with self.db.project(project_id, project.folder_path) as session:
            query = select(ChangeProposal).options(selectinload(ChangeProposal.operations), selectinload(ChangeProposal.impacts)).order_by(ChangeProposal.created_at.desc())
            if status:
                query = query.where(ChangeProposal.status == status)
            return [self._proposal_dict(item) for item in session.scalars(query).all()]

    def apply_proposal(self, proposal_id: str, payload: ProposalApply, request_id: str) -> dict[str, Any]:
        project = self.get_project(payload.project_id)
        with self.db.project_write(project.id, project.folder_path) as session:
            proposal = session.scalar(select(ChangeProposal).where(ChangeProposal.id == proposal_id).options(selectinload(ChangeProposal.operations), selectinload(ChangeProposal.impacts)))
            if not proposal:
                raise StoryError(404, "PROPOSAL_NOT_FOUND", "修改提案不存在。")
            if proposal.revision != payload.expected_revision:
                raise StoryError(409, "REVISION_CONFLICT", "修改提案已被其他操作处理。", {"currentRevision": proposal.revision})
            if proposal.status != "pending":
                raise StoryError(409, "PROPOSAL_ALREADY_RESOLVED", "修改提案已处理。", {"status": proposal.status})
            node = session.get(PlanNode, proposal.target_id)
            if not node:
                raise StoryError(404, "PLAN_NODE_NOT_FOUND", "提案目标节点不存在。")
            before = self._node_dict(node)
            selected = set(payload.selected_operation_ids)
            applied = []
            for operation in proposal.operations:
                operation.selected = operation.id in selected
                if operation.selected:
                    self._apply_proposal_operation(node, operation)
                    applied.append(operation.id)
            if not applied:
                raise StoryError(422, "NO_OPERATIONS_SELECTED", "至少选择一项修改。")
            self._validate_node(node)
            self._validate_proposal_dependencies(session, node, self._node_dict(node))
            node.revision += 1
            proposal.status = "accepted"
            proposal.revision += 1
            proposal.updated_at = utc_now()
            session.add(self._audit("proposal.applied", "plan_node", node.id, {"proposalId": proposal.id, "operationIds": applied, "before": before, "after": self._node_dict(node), "reversible": True}, request_id))
            session.flush()
            return self._proposal_dict(proposal)

    def reject_proposal(self, proposal_id: str, payload: ProposalReject, request_id: str) -> dict[str, Any]:
        project = self.get_project(payload.project_id)
        with self.db.project_write(project.id, project.folder_path) as session:
            proposal = session.scalar(select(ChangeProposal).where(ChangeProposal.id == proposal_id).options(selectinload(ChangeProposal.operations), selectinload(ChangeProposal.impacts)))
            if not proposal:
                raise StoryError(404, "PROPOSAL_NOT_FOUND", "修改提案不存在。")
            if proposal.revision != payload.expected_revision:
                raise StoryError(409, "REVISION_CONFLICT", "修改提案已被其他操作处理。")
            if proposal.status != "pending":
                raise StoryError(409, "PROPOSAL_ALREADY_RESOLVED", "修改提案已处理。")
            proposal.status = "rejected"
            proposal.revision += 1
            proposal.updated_at = utc_now()
            session.add(self._audit("proposal.rejected", "change_proposal", proposal.id, {"proposalId": proposal.id, "reversible": False}, request_id))
            session.flush()
            return self._proposal_dict(proposal)

    def list_audit_events(self, project_id: str, limit: int = 100, event_type: str | None = None, entity_type: str | None = None) -> list[dict[str, Any]]:
        project = self.get_project(project_id)
        with self.db.project(project.id, project.folder_path) as session:
            query = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(min(limit, 500))
            if event_type:
                query = query.where(AuditEvent.event_type == event_type)
            if entity_type:
                query = query.where(AuditEvent.entity_type == entity_type)
            events = session.scalars(query).all()
            return [self._audit_dict(item) for item in events]

    def undo_event(self, project_id: str, event_id: str, request_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        with self.db.project_write(project.id, project.folder_path) as session:
            event = session.get(AuditEvent, event_id)
            if not event:
                raise StoryError(404, "AUDIT_EVENT_NOT_FOUND", "审计事件不存在。")
            payload = loads(event.payload_json)
            if not payload.get("reversible") or not payload.get("before"):
                raise StoryError(409, "EVENT_NOT_REVERSIBLE", "该事件不能撤销。")
            node = session.get(PlanNode, event.entity_id)
            if not node:
                raise StoryError(404, "PLAN_NODE_NOT_FOUND", "撤销目标不存在。")
            current = self._node_dict(node)
            expected_after = payload.get("after", {})
            if current.get("revision") != expected_after.get("revision"):
                raise StoryError(409, "REVISION_CONFLICT", "节点在该操作后又发生变化，不能直接撤销。", {"currentRevision": current.get("revision")})
            before = payload["before"]
            self._apply_node_snapshot(node, before)
            node.revision = current["revision"] + 1
            undo = self._audit("event.undone", "plan_node", node.id, {"undoneEventId": event.id, "before": current, "after": self._node_dict(node), "reversible": False}, request_id)
            session.add(undo)
            session.flush()
            return self._audit_dict(undo)

    def create_backup(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        folder = Path(project.folder_path)
        backup_id = str(uuid4())
        created = utc_now()
        archive = folder / "backups" / f"{created.strftime('%Y%m%d-%H%M%S')}-{backup_id}.zip"
        with tempfile.TemporaryDirectory(dir=self.settings.data_dir) as temp_name:
            temp = Path(temp_name)
            db_snapshot = temp / "story.db"
            source = sqlite3.connect(folder / "story.db")
            target = sqlite3.connect(db_snapshot)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            files: dict[str, Path] = {"project.json": folder / "project.json", "story.db": db_snapshot}
            for canon_file in (folder / "canon").rglob("*"):
                if canon_file.is_file():
                    files[canon_file.relative_to(folder).as_posix()] = canon_file
            for manuscript_file in (folder / "manuscripts").rglob("*"):
                if manuscript_file.is_file():
                    files[manuscript_file.relative_to(folder).as_posix()] = manuscript_file
            checksums = {name: sha256(path) for name, path in files.items()}
            manifest = {
                "backupId": backup_id, "projectId": project.id, "projectTitle": project.title,
                "createdAt": created.isoformat(), "files": checksums,
            }
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
                for name, path in files.items():
                    package.write(path, name)
                package.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return {**manifest, "archivePath": str(archive)}

    def list_backups(self, project_id: str) -> list[dict[str, Any]]:
        project = self.get_project(project_id)
        folder = Path(project.folder_path)
        backups: list[dict[str, Any]] = []
        for archive in sorted((folder / "backups").glob("*.zip"), key=lambda path: path.stat().st_mtime, reverse=True):
            try:
                item = self._read_backup_manifest(archive, require_checksums=False)
            except StoryError:
                item = {
                    "backupId": archive.stem,
                    "projectId": project.id,
                    "projectTitle": project.title,
                    "createdAt": datetime.fromtimestamp(archive.stat().st_mtime, tz=timezone.utc).isoformat(),
                    "files": {},
                }
            item["archivePath"] = str(archive)
            item["sizeBytes"] = archive.stat().st_size
            item["isValid"] = self._backup_archive_is_valid(archive)
            backups.append(item)
        return backups

    def backup_archive_path(self, project_id: str, backup_id: str) -> Path:
        project = self.get_project(project_id)
        folder = Path(project.folder_path)
        for archive in (folder / "backups").glob("*.zip"):
            try:
                manifest = self._read_backup_manifest(archive, require_checksums=False)
            except StoryError:
                if archive.stem == backup_id:
                    return archive
                continue
            if manifest.get("backupId") == backup_id:
                return archive
        raise StoryError(404, "BACKUP_NOT_FOUND", "备份不存在。", {"backupId": backup_id})

    def restore_backup(self, archive_path: Path) -> CatalogProject:
        manifest = self._read_backup_manifest(archive_path, require_checksums=True)
        with tempfile.TemporaryDirectory(dir=self.settings.data_dir) as temp_name:
            temp = Path(temp_name)
            with zipfile.ZipFile(archive_path) as package:
                for name in manifest["files"]:
                    safe_name = self._safe_backup_member(name)
                    destination = temp / Path(*PurePosixPath(safe_name).parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with package.open(name) as source, destination.open("wb") as target:
                        shutil.copyfileobj(source, target)
            try:
                source_json = json.loads((temp / "project.json").read_text(encoding="utf-8"))
                source_project_id = str(source_json["id"])
                source_title = str(source_json["title"])
                source_mode = str(source_json["mode"])
                source_total = int(source_json["totalChapters"])
                source_current = int(source_json.get("currentChapter", 0))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise StoryError(422, "INVALID_BACKUP_PROJECT", "备份中的 project.json 无效。") from exc
            if source_current < 0 or source_current > source_total:
                raise StoryError(422, "INVALID_BACKUP_PROJECT", "备份中的当前章节超出作品范围。")

            restored: CatalogProject | None = None
            try:
                restored = self.create_project(ProjectCreate(
                    title=f"{source_title}（恢复）", mode=source_mode, total_chapters=source_total
                ))
                target_folder = Path(restored.folder_path)
                engine = self.db._project_engines.pop(restored.id, None)
                self.db._project_factories.pop(restored.id, None)
                if engine:
                    engine.dispose()
                shutil.copy2(temp / "story.db", target_folder / "story.db")
                if (temp / "canon").exists():
                    for canon_file in (temp / "canon").rglob("*"):
                        if canon_file.is_file():
                            destination = target_folder / canon_file.relative_to(temp)
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(canon_file, destination)
                if (temp / "manuscripts").exists():
                    for manuscript_file in (temp / "manuscripts").rglob("*"):
                        if manuscript_file.is_file():
                            destination = target_folder / manuscript_file.relative_to(temp)
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(manuscript_file, destination)
                self.db.ensure_project_database(restored.id, target_folder)
                with self.db.project_write(restored.id, target_folder) as session:
                    old_meta = session.scalar(select(ProjectMeta))
                    if not old_meta:
                        raise StoryError(422, "INVALID_BACKUP_DATABASE", "备份数据库缺少作品元数据。")
                    old_id = source_project_id
                    if old_meta.id != old_id:
                        raise StoryError(422, "INVALID_BACKUP_DATABASE", "备份数据库与 project.json 的作品 ID 不一致。")
                    old_meta.id = restored.id
                    old_meta.title = restored.title
                    old_meta.mode = source_mode
                    old_meta.current_chapter = source_current
                    old_meta.total_chapters = source_total
                    for agent_session in session.scalars(select(AgentSession).where(AgentSession.project_id == old_id)):
                        agent_session.project_id = restored.id
                    # A restored project receives a new catalog/project ID. All
                    # phase-four rows are scoped by that ID even though each
                    # project already has its own SQLite file, so remap them in
                    # the same transaction before exposing the restored work.
                    for table_name in (
                        "canon_change_requests",
                        "source_versions",
                        "story_entities",
                        "state_facts",
                        "story_events",
                        "state_deltas",
                        "foreshadows",
                        "knowledge_boundaries",
                        "state_snapshots",
                        "context_traces",
                        "chapter_contracts",
                        "chapter_jobs",
                        "chapter_drafts",
                        "chapter_extractions",
                        "quality_runs",
                        "quality_findings",
                        "chapter_commits",
                        "automation_policies",
                        "automation_runs",
                        "automation_run_items",
                        "automation_leases",
                        "automation_daily_reports",
                        "export_profiles",
                        "export_jobs",
                        "export_job_chapters",
                        "export_artifacts",
                        "publication_records",
                        "endurance_suites",
                        "endurance_runs",
                        "endurance_checkpoints",
                        "endurance_findings",
                        "endurance_reports",
                    ):
                        session.execute(text(
                            f"UPDATE {table_name} SET project_id = :new_id WHERE project_id = :old_id"
                        ), {"new_id": restored.id, "old_id": old_id})
                    # AutomationPolicy uses project_id as its identity. Runs
                    # keep a separate policy_id reference, so remap that
                    # reference as part of the same restore transaction too.
                    session.execute(text(
                        "UPDATE automation_runs SET policy_id = :new_id WHERE policy_id = :old_id"
                    ), {"new_id": restored.id, "old_id": old_id})
                    # Export files are intentionally excluded from backups.
                    # Preserve audit metadata in restored clones, but force
                    # artifact rows into a non-downloadable missing state.
                    session.execute(text(
                        "UPDATE export_artifacts SET status = 'missing', relative_path = '', is_current = 0, revision = revision + 1 WHERE project_id = :new_id"
                    ), {"new_id": restored.id})
                    session.execute(text(
                        "UPDATE endurance_runs SET status = 'interrupted', stop_reason = 'backup_restore', current_automation_run_id = NULL, current_automation_run_item_id = NULL, completed_at = :now WHERE project_id = :new_id AND status IN ('queued','running','paused','cancel_requested')"
                    ), {"new_id": restored.id, "now": utc_now()})
                    # Lease rows are runtime ownership, not transferable
                    # authority. Keep them in the backup for auditability, but
                    # never let a restored clone inherit another process lease.
                    session.execute(text("DELETE FROM automation_leases"))
                    index_state = session.get(RetrievalIndexState, old_id)
                    if index_state:
                        index_state.project_id = restored.id
                    # Retrieval is derived data. Removing the copied rows and
                    # rebuilding avoids carrying stale namespace identifiers.
                    session.execute(text("DELETE FROM retrieval_fts"))
                    session.execute(text("DELETE FROM retrieval_index_entries"))
                    self.phase4._rebuild_retrieval_index(session, restored.id, utc_now())
                with self.db.catalog() as session:
                    catalog = session.get(CatalogProject, restored.id)
                    assert catalog
                    catalog.current_chapter = source_current
                    catalog.total_chapters = source_total
                    catalog.mode = source_mode
                    catalog.updated_at = utc_now()
                    session.commit()
                    session.refresh(catalog)
                    restored = catalog
                self._write_project_files(restored)
                # With runtime leases cleared, active copied runs/jobs converge
                # to interrupted and require an explicit resume in the clone.
                self.phase7.reconcile_orphaned_automation()
                self._repair_restored_export_metadata(restored, old_id)
                return restored
            except Exception:
                if restored is not None:
                    self._remove_failed_restore(restored)
                raise

    def _repair_restored_export_metadata(self, project: CatalogProject, source_project_id: str) -> None:
        """Finalize project identity embedded in copied Phase 9 JSON payloads.

        Bulk SQL remaps the relational scope during restore. This second short
        transaction intentionally runs after the copied database transaction
        has committed so ORM state or startup reconciliation cannot restore a
        stale source project ID in an export manifest.
        """
        with self.db.project_write(project.id, project.folder_path) as session:
            manifest_by_job: dict[str, dict[str, Any]] = {}
            for export_job in session.scalars(select(ExportJob)).all():
                export_job.project_id = project.id
                export_job.readiness_json = dumps(remap_json_identifier(
                    safe_json_loads(export_job.readiness_json, {}), source_project_id, project.id
                ))
                if export_job.diagnostic_json:
                    export_job.diagnostic_json = dumps(remap_json_identifier(
                        safe_json_loads(export_job.diagnostic_json, {}), source_project_id, project.id
                    ))
                manifest = safe_json_loads(export_job.frozen_manifest_json, {})
                if isinstance(manifest, dict) and manifest:
                    manifest = remap_json_identifier(manifest, source_project_id, project.id)
                    manifest["projectId"] = project.id
                    manifest.pop("manifestChecksum", None)
                    manifest["manifestChecksum"] = stable_digest(manifest)
                    export_job.frozen_manifest_json = dumps(manifest)
                    manifest_by_job[export_job.id] = manifest
            for artifact in session.scalars(select(ExportArtifact)).all():
                artifact.project_id = project.id
                manifest = manifest_by_job.get(artifact.export_job_id)
                if manifest:
                    artifact.manifest_json = dumps(manifest)
            for chapter in session.scalars(select(ExportJobChapter)).all():
                chapter.project_id = project.id
                chapter.quality_summary_json = dumps(remap_json_identifier(
                    safe_json_loads(chapter.quality_summary_json, {}), source_project_id, project.id
                ))
                chapter.issue_summary_json = dumps(remap_json_identifier(
                    safe_json_loads(chapter.issue_summary_json, []), source_project_id, project.id
                ))

    def _read_backup_manifest(self, archive: Path, *, require_checksums: bool) -> dict[str, Any]:
        if not zipfile.is_zipfile(archive):
            raise StoryError(422, "INVALID_BACKUP", "备份文件不是有效 ZIP。")
        with zipfile.ZipFile(archive) as package:
            names = set(package.namelist())
            if "manifest.json" not in names:
                raise StoryError(422, "INVALID_BACKUP", "备份缺少 manifest.json。")
            try:
                manifest = json.loads(package.read("manifest.json"))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
                raise StoryError(422, "INVALID_BACKUP_MANIFEST", "备份清单无法解析。") from exc
            if not isinstance(manifest, dict) or not all(isinstance(manifest.get(field), str) and manifest[field] for field in ("backupId", "projectId", "projectTitle", "createdAt")) or not isinstance(manifest.get("files"), dict):
                raise StoryError(422, "INVALID_BACKUP_MANIFEST", "备份清单结构无效。")
            try:
                datetime.fromisoformat(manifest["createdAt"].replace("Z", "+00:00"))
            except ValueError as exc:
                raise StoryError(422, "INVALID_BACKUP_MANIFEST", "备份清单时间无效。") from exc
            if not all(isinstance(name, str) and isinstance(digest, str) for name, digest in manifest["files"].items()):
                raise StoryError(422, "INVALID_BACKUP_MANIFEST", "备份清单文件列表无效。")
            if require_checksums:
                if len(names) > 10_000 or sum(info.file_size for info in package.infolist()) > 1024 * 1024 * 1024:
                    raise StoryError(422, "BACKUP_TOO_LARGE", "备份展开后超过安全限制。")
                for name in names:
                    self._safe_backup_member(name)
                if not {"project.json", "story.db"}.issubset(manifest["files"]):
                    raise StoryError(422, "INVALID_BACKUP_MANIFEST", "备份清单缺少必要文件。")
                for name, expected in manifest.get("files", {}).items():
                    self._safe_backup_member(name)
                    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected) or name not in names:
                        raise StoryError(422, "BACKUP_CHECKSUM_MISMATCH", "备份校验失败。", {"path": name})
                    digest = hashlib.sha256()
                    with package.open(name) as handle:
                        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                            digest.update(chunk)
                    if digest.hexdigest() != expected:
                        raise StoryError(422, "BACKUP_CHECKSUM_MISMATCH", "备份校验失败。", {"path": name})
            return manifest

    def _safe_backup_member(self, name: str) -> str:
        if not isinstance(name, str) or not name or "\\" in name:
            raise StoryError(422, "INVALID_BACKUP_PATH", "备份包含不安全路径。", {"path": name})
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or (path.parts and ":" in path.parts[0]):
            raise StoryError(422, "INVALID_BACKUP_PATH", "备份包含不安全路径。", {"path": name})
        return path.as_posix()

    def _remove_failed_restore(self, project: CatalogProject) -> None:
        engine = self.db._project_engines.pop(project.id, None)
        self.db._project_factories.pop(project.id, None)
        if engine:
            engine.dispose()
        with self.db.catalog() as session:
            row = session.get(CatalogProject, project.id)
            if row:
                session.delete(row)
                session.commit()
        folder = Path(project.folder_path).resolve()
        if self.settings.projects_dir.resolve() in folder.parents:
            shutil.rmtree(folder, ignore_errors=True)

    def _backup_archive_is_valid(self, archive: Path) -> bool:
        try:
            self._read_backup_manifest(archive, require_checksums=True)
            return True
        except StoryError:
            return False

    def _validate_base_url(self, value: str) -> None:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise StoryError(422, "INVALID_MODEL_BASE_URL", "模型服务地址必须是有效的 HTTP(S) URL。")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise StoryError(422, "INVALID_MODEL_BASE_URL", "模型服务地址不得包含账号、密码、查询参数或片段。")
        if parsed.scheme == "https":
            return
        host = (parsed.hostname or "").lower()
        if host not in {"localhost", "127.0.0.1"}:
            raise StoryError(422, "INSECURE_MODEL_BASE_URL", "模型服务地址默认必须使用 HTTPS；仅 localhost 与 127.0.0.1 允许 HTTP。")

    def _store_provider_secret(self, provider: ModelProvider, key_ref: str, secret: str) -> None:
        try:
            self.secret_store.set_secret(key_ref, secret)
        except SecretStoreUnavailable:
            raise StoryError(503, "CREDENTIAL_STORE_UNAVAILABLE", "Credential Manager 不可用，无法保存 API Key。")
        provider.api_key_ref = key_ref
        provider.api_key_preview = secret_preview(secret)

    def _delete_provider_secret(self, key_ref: str) -> None:
        try:
            self.secret_store.delete_secret(key_ref)
        except SecretStoreUnavailable:
            raise StoryError(503, "CREDENTIAL_STORE_UNAVAILABLE", "Credential Manager 不可用，无法删除 API Key。")

    def _connection_result(self, provider: dict[str, Any], ok: bool, status: str, model: str | None, message: str) -> dict[str, Any]:
        return {
            "ok": ok,
            "status": status,
            "providerId": provider["id"],
            "providerName": provider["name"],
            "model": model,
            "message": message,
        }

    async def _stream_structured_proposal(self, project_id: str, folder_path: str, session_id: str, payload: AgentMessageCreate, request_id: str) -> AsyncIterator[dict[str, Any]]:
        run_id = str(uuid4())
        started = time.perf_counter()
        compiled = self._prepare_model_call(project_id, folder_path, session_id, payload, "planner", run_id, request_id, run_role="planner_proposal", create_user_message=False)
        provider = OpenAICompatibleModelProvider(
            base_url=compiled["baseUrl"],
            api_key=compiled["apiKey"],
            timeout_seconds=compiled["timeoutSeconds"],
            max_retries=compiled["maxRetries"],
        )
        attempts = 0
        last_failure: tuple[str, str] | None = None
        try:
            yield {"event": "proposal_started", "runId": run_id, "provider": compiled["providerName"], "model": compiled["modelId"], "requestId": request_id}
            while attempts < 2:
                attempts += 1
                if run_id in self._cancelled_runs:
                    self._complete_model_run_failure(project_id, folder_path, session_id, run_id, "cancelled", "cancelled", started, retry_count=provider.last_result.retry_count)
                    yield {"event": "cancelled", "runId": run_id, "message": "结构化提案生成已停止。"}
                    return
                proposal_payload = self._structured_proposal_payload(compiled["payload"], payload, last_failure)
                try:
                    result = await provider.complete_chat(proposal_payload)
                    if run_id in self._cancelled_runs:
                        self._complete_model_run_failure(project_id, folder_path, session_id, run_id, "cancelled", "cancelled", started, retry_count=result.retry_count)
                        yield {"event": "cancelled", "runId": run_id, "message": "结构化提案生成已停止。"}
                        return
                    proposal = self._parse_structured_proposal_text(result.text)
                    created = self._create_structured_proposal(project_id, folder_path, proposal, run_id, request_id)
                    self._complete_model_run_success(project_id, folder_path, session_id, run_id, "", result, started, create_message=False, diagnostic={
                        "kind": "structured_proposal",
                        "action": payload.action,
                        "attempts": attempts,
                        "proposalId": created["id"],
                    })
                    yield {"event": "proposal_completed", "runId": run_id, "proposal": created, "attempts": attempts}
                    return
                except ModelProviderError as exc:
                    if exc.code == "content_truncated" and attempts == 1:
                        last_failure = (exc.code, exc.message)
                        continue
                    raise
                except StoryError as exc:
                    if exc.code in {"EMPTY_PROPOSAL_JSON", "INVALID_PROPOSAL_JSON", "INVALID_PROPOSAL_STRUCTURE"} and attempts == 1:
                        last_failure = (exc.code, exc.message)
                        continue
                    if payload.action == "logic_check" and exc.code in {"PROPOSAL_NO_OPERATIONS", "PROPOSAL_NO_EFFECT"}:
                        self._complete_model_run_success(project_id, folder_path, session_id, run_id, "", result, started, create_message=False, diagnostic={
                            "kind": "structured_proposal",
                            "action": payload.action,
                            "attempts": attempts,
                            "reason": exc.code,
                            "message": exc.message,
                        })
                        self._record_proposal_noop(project_id, folder_path, payload.selected_node_id, exc.code, exc.message, request_id, run_id)
                        yield {"event": "proposal_skipped", "runId": run_id, "reasonCode": exc.code, "message": exc.message, "attempts": attempts}
                        return
                    self._complete_model_run_failure(project_id, folder_path, session_id, run_id, "failed", exc.code, started, diagnostic={
                        "kind": "structured_proposal",
                        "action": payload.action,
                        "attempts": attempts,
                        "reason": exc.code,
                        "message": exc.message,
                    }, retry_count=result.retry_count)
                    self._record_proposal_failure(project_id, folder_path, payload.selected_node_id, exc.code, exc.message, request_id, run_id)
                    yield {"event": "proposal_failed", "runId": run_id, "errorCode": exc.code, "message": exc.message, "attempts": attempts}
                    return
            code, message = last_failure or ("INVALID_PROPOSAL_JSON", "模型没有返回可用提案。")
            self._complete_model_run_failure(project_id, folder_path, session_id, run_id, "failed", code, started, diagnostic={
                "kind": "structured_proposal",
                "action": payload.action,
                "attempts": attempts,
                "reason": code,
            }, retry_count=provider.last_result.retry_count)
            self._record_proposal_failure(project_id, folder_path, payload.selected_node_id, code, message, request_id, run_id)
            yield {"event": "proposal_failed", "runId": run_id, "errorCode": code, "message": message, "attempts": attempts}
        except ModelProviderError as exc:
            self._complete_model_run_failure(project_id, folder_path, session_id, run_id, "failed", exc.code, started, diagnostic={
                "kind": "structured_proposal",
                "action": payload.action,
                "attempts": attempts,
                "reason": exc.code,
            }, retry_count=provider.last_result.retry_count)
            self._record_proposal_failure(project_id, folder_path, payload.selected_node_id, exc.code, exc.message, request_id, run_id)
            yield {"event": "proposal_failed", "runId": run_id, "errorCode": exc.code, "message": exc.message, "attempts": attempts}
        except (asyncio.CancelledError, GeneratorExit):
            self._cancelled_runs.add(run_id)
            self._complete_model_run_failure(project_id, folder_path, session_id, run_id, "cancelled", "client_disconnected", started, retry_count=provider.last_result.retry_count)
            raise
        finally:
            self._cancelled_runs.discard(run_id)

    def _structured_proposal_payload(self, base_payload: dict[str, Any], payload: AgentMessageCreate, last_failure: tuple[str, str] | None) -> dict[str, Any]:
        messages = list(base_payload["messages"])
        repair = ""
        if last_failure:
            repair = f"\n上一次结构化输出失败：{last_failure[0]} - {last_failure[1]}。请只返回可解析 JSON，不要 Markdown，不要解释。"
        messages.append({
            "role": "system",
            "content": (
                "现在执行结构化规划提案。只返回 JSON object。"
                "不得直接修改正式规划；只能描述待用户确认的提案。"
                "只能使用白名单字段；不要包含正文、API Key、完整上下文或额外字段。"
            ),
        })
        messages.append({
            "role": "user",
            "content": (
                f"用户动作：{payload.action}\n"
                f"输出 JSON Schema 说明：{json.dumps(JSON_PROPOSAL_SCHEMA_HINT, ensure_ascii=False)}\n"
                "如果只是逻辑检查且不建议改动，也必须给出 operations 为空的明确 reason。"
                f"{repair}"
            ),
        })
        return {
            **base_payload,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": min(float(base_payload.get("temperature", 0.2)), 0.2),
        }

    def _parse_structured_proposal_text(self, text: str) -> dict[str, Any]:
        if not text or not text.strip():
            raise StoryError(422, "EMPTY_PROPOSAL_JSON", "模型没有返回结构化提案 JSON。")
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise StoryError(422, "INVALID_PROPOSAL_JSON", "模型返回的结构化提案不是合法 JSON。") from exc
        if not isinstance(data, dict):
            raise StoryError(422, "INVALID_PROPOSAL_STRUCTURE", "结构化提案必须是 JSON object。")
        return data

    def _create_structured_proposal(self, project_id: str, folder_path: str, raw: dict[str, Any], run_id: str, request_id: str) -> dict[str, Any]:
        allowed_top = {"targetId", "expectedRevision", "reason", "operations", "impacts"}
        extra = sorted(set(raw) - allowed_top)
        if extra:
            raise StoryError(422, "PROPOSAL_TOP_LEVEL_NOT_ALLOWED", "结构化提案包含不允许的顶层字段。", {"fields": extra})
        target_id = raw.get("targetId")
        if not isinstance(target_id, str) or not target_id.strip():
            raise StoryError(422, "PROPOSAL_TARGET_REQUIRED", "结构化提案缺少目标里程碑。")
        operations = raw.get("operations")
        if not isinstance(operations, list):
            raise StoryError(422, "INVALID_PROPOSAL_STRUCTURE", "结构化提案 operations 必须是数组。")
        if not operations:
            raise StoryError(422, "PROPOSAL_NO_OPERATIONS", "结构化提案没有可确认的修改项。")
        reason = raw.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise StoryError(422, "PROPOSAL_REASON_REQUIRED", "结构化提案缺少修改原因。")
        with self.db.project_write(project_id, folder_path) as session:
            node = session.get(PlanNode, target_id)
            if not node:
                raise StoryError(422, "PROPOSAL_TARGET_NOT_FOUND", "结构化提案目标不存在。", {"targetId": target_id})
            expected_revision = raw.get("expectedRevision")
            if not isinstance(expected_revision, int) or expected_revision != node.revision:
                raise StoryError(409, "PROPOSAL_REVISION_CONFLICT", "模型提案基于过期规划版本。", {"targetId": target_id, "currentRevision": node.revision})
            proposal = self._proposal_from_structured(session, node, raw)
            session.add(proposal)
            session.add(self._audit("proposal.generated", "change_proposal", proposal.id, {
                "runId": run_id,
                "targetId": node.id,
                "operationCount": len(proposal.operations),
                "reversible": False,
            }, request_id))
            session.flush()
            return self._proposal_dict(proposal)

    def _proposal_from_structured(self, session: Session, node: PlanNode, raw: dict[str, Any]) -> ChangeProposal:
        proposal_id = str(uuid4())
        proposal = ChangeProposal(
            id=proposal_id,
            target_id=node.id,
            target_title=node.title,
            reason=raw["reason"].strip(),
        )
        before = self._node_dict(node)
        simulated = self._node_dict(node)
        proposal.operations = []
        for item in raw["operations"]:
            if not isinstance(item, dict):
                raise StoryError(422, "INVALID_PROPOSAL_OPERATION", "提案操作必须是 JSON object。")
            extra = sorted(set(item) - {"field", "after", "label"})
            if extra:
                raise StoryError(422, "PROPOSAL_OPERATION_FIELD_NOT_ALLOWED", "提案操作包含不允许字段。", {"fields": extra})
            field = item.get("field")
            if field not in PROPOSAL_FIELD_MAP:
                raise StoryError(422, "PROPOSAL_FIELD_NOT_ALLOWED", "提案试图修改非白名单字段。", {"field": field})
            _attr, default_label, value_type = PROPOSAL_FIELD_MAP[field]
            after = self._coerce_proposal_value(field, item.get("after"), value_type)
            before_value = before[field]
            if after == before_value:
                continue
            simulated[field] = after
            before_int = before_value if isinstance(before_value, int) else 0
            after_int = after if isinstance(after, int) else 0
            proposal.operations.append(ChangeOperation(
                id=str(uuid4()),
                proposal_id=proposal_id,
                field=field,
                label=item.get("label") if isinstance(item.get("label"), str) and item.get("label") else default_label,
                before_value=before_int,
                after_value=after_int,
                before_json=dumps(before_value),
                after_json=dumps(after),
                selected=True,
            ))
        if not proposal.operations:
            raise StoryError(422, "PROPOSAL_NO_EFFECT", "结构化提案没有产生实际变化。")
        self._validate_node_snapshot(simulated)
        self._validate_proposal_dependencies(session, node, simulated)
        impacts = raw.get("impacts") if isinstance(raw.get("impacts"), list) else []
        proposal.impacts = self._proposal_impacts_from_structured(proposal_id, impacts, proposal.operations)
        return proposal

    def _coerce_proposal_value(self, field: str, value: Any, value_type: str) -> Any:
        if value_type == "integer":
            if not isinstance(value, int):
                raise StoryError(422, "INVALID_PROPOSAL_VALUE", "章节字段必须是整数。", {"field": field})
            if value < 1 or value > 5000:
                raise StoryError(422, "INVALID_PROPOSAL_VALUE", "章节字段超出允许范围。", {"field": field})
            return value
        if value_type == "list":
            if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
                raise StoryError(422, "INVALID_PROPOSAL_VALUE", "依赖和契约字段必须是非空字符串数组。", {"field": field})
            return [item.strip()[:240] for item in value[:20]]
        if value_type == "string":
            if not isinstance(value, str):
                raise StoryError(422, "INVALID_PROPOSAL_VALUE", "文本字段必须是字符串。", {"field": field})
            text = value.strip()
            if field == "pace" and text not in {"smooth", "fast", "slow"}:
                raise StoryError(422, "INVALID_PROPOSAL_VALUE", "节奏状态必须是 smooth、fast 或 slow。", {"field": field})
            return text[:2000]
        raise StoryError(422, "INVALID_PROPOSAL_VALUE", "提案字段类型无效。", {"field": field})

    def _validate_node_snapshot(self, data: dict[str, Any]) -> None:
        if data["rangeMin"] > data["rangeMax"]:
            raise StoryError(422, "INVALID_CHAPTER_RANGE", "允许范围起点不能晚于终点。")
        if data["targetChapter"] < data["rangeMin"] or data["targetChapter"] > data["rangeMax"]:
            raise StoryError(422, "TARGET_OUTSIDE_RANGE", "目标章节必须位于允许范围内。", {"targetChapter": data["targetChapter"], "rangeMin": data["rangeMin"], "rangeMax": data["rangeMax"]})
        if not data["prerequisites"] or not data["completionConditions"]:
            raise StoryError(422, "INCOMPLETE_MILESTONE_CONTRACT", "里程碑必须包含前置条件和完成条件。")

    def _validate_proposal_dependencies(self, session: Session, node: PlanNode, snapshot: dict[str, Any]) -> None:
        existing_ids = set(session.scalars(select(PlanNode.id)).all())
        for field in ("prerequisites", "completionConditions", "foreshadows", "contracts"):
            values = snapshot.get(field, [])
            if not isinstance(values, list):
                raise StoryError(422, "INVALID_PROPOSAL_VALUE", "依赖字段结构无效。", {"field": field})
            for value in values:
                if not isinstance(value, str) or len(value) > 240:
                    raise StoryError(422, "INVALID_PROPOSAL_VALUE", "依赖条目必须是短字符串。", {"field": field})
                if value.startswith("node:"):
                    target_id = value[5:]
                    if target_id not in existing_ids:
                        raise StoryError(422, "PROPOSAL_DEPENDENCY_NOT_FOUND", "提案引用了不存在的依赖节点。", {"field": field, "dependency": value})
                    if target_id == node.id:
                        raise StoryError(422, "PROPOSAL_DEPENDENCY_SELF_REFERENCE", "提案不能引用自身作为依赖。", {"field": field})

    def _proposal_impacts_from_structured(self, proposal_id: str, impacts: list[Any], operations: list[ChangeOperation]) -> list[ProposalImpact]:
        allowed_kinds = {"contract", "foreshadow", "dependency", "pace", "chapter_window"}
        result: list[ProposalImpact] = []
        for item in impacts[:12]:
            if not isinstance(item, dict):
                continue
            kind = item.get("kind")
            label = item.get("label")
            if kind not in allowed_kinds or not isinstance(label, str) or not label.strip():
                continue
            result.append(ProposalImpact(id=str(uuid4()), proposal_id=proposal_id, kind=kind, label=label.strip()[:200]))
        if result:
            return result
        touched = {operation.field for operation in operations}
        if touched & {"targetChapter", "rangeMin", "rangeMax"}:
            result.append(ProposalImpact(id=str(uuid4()), proposal_id=proposal_id, kind="chapter_window", label="章节窗口将随提案调整"))
        if touched & {"prerequisites", "completionConditions", "contracts"}:
            result.append(ProposalImpact(id=str(uuid4()), proposal_id=proposal_id, kind="dependency", label="依赖与章节契约将随提案调整"))
        if touched & {"foreshadows"}:
            result.append(ProposalImpact(id=str(uuid4()), proposal_id=proposal_id, kind="foreshadow", label="伏笔清单将随提案调整"))
        return result

    def _record_proposal_failure(self, project_id: str, folder_path: str, target_id: str | None, code: str, message: str, request_id: str, run_id: str) -> None:
        with self.db.project_write(project_id, folder_path) as session:
            session.add(self._audit("proposal.generation_failed", "plan_node", target_id or "unknown", {
                "runId": run_id,
                "code": code,
                "message": message,
                "reversible": False,
            }, request_id))

    def _record_proposal_noop(self, project_id: str, folder_path: str, target_id: str | None, code: str, message: str, request_id: str, run_id: str) -> None:
        with self.db.project_write(project_id, folder_path) as session:
            session.add(self._audit("proposal.noop", "plan_node", target_id or "unknown", {
                "runId": run_id,
                "code": code,
                "message": message,
                "reversible": False,
            }, request_id))

    def _prepare_model_call(self, project_id: str, folder_path: str, session_id: str, payload: AgentMessageCreate, role: str, run_id: str, request_id: str, *, run_role: str | None = None, create_user_message: bool = True) -> dict[str, Any]:
        model_info = self._resolve_role_model(role)
        if not model_info:
            raise StoryError(409, "MODEL_ROLE_NOT_CONFIGURED", "规划 Agent 尚未绑定模型，请先前往模型与费用设置。", {"role": role})
        if not model_info["provider"].is_enabled or not model_info["model"].is_enabled:
            raise StoryError(409, "MODEL_DISABLED", "已绑定模型或 Provider 未启用。", {"role": role})
        provider = model_info["provider"]
        model = model_info["model"]
        if not provider.api_key_ref:
            raise StoryError(409, "MODEL_API_KEY_MISSING", "Provider 尚未保存 API Key。", {"providerId": provider.id})
        try:
            api_key = self.secret_store.get_secret(provider.api_key_ref)
        except SecretStoreUnavailable:
            raise StoryError(503, "CREDENTIAL_STORE_UNAVAILABLE", "Credential Manager 不可用，无法读取 API Key。")
        if not api_key:
            raise StoryError(409, "MODEL_API_KEY_MISSING", "Credential Manager 中未找到 Provider API Key。", {"providerId": provider.id})

        context = self._compile_agent_context(project_id, folder_path, session_id, payload)
        now = utc_now()
        with self.db.project_write(project_id, folder_path) as session:
            agent_session = session.get(AgentSession, session_id)
            if not agent_session:
                raise StoryError(404, "AGENT_SESSION_NOT_FOUND", "Agent 会话不存在。")
            if create_user_message:
                session.add(AgentMessage(id=str(uuid4()), session_id=session_id, role="user", content=payload.content, created_at=now))
            session.add(ModelRun(
                id=run_id,
                session_id=session_id,
                role=run_role or role,
                provider_id=provider.id,
                provider_name=provider.name,
                model_config_id=model.id,
                model_id=model.model_id,
                status="running",
                request_id=request_id,
                retry_count=0,
                started_at=now,
            ))
            agent_session.status = "thinking"
            agent_session.updated_at = now
        messages = [
            {"role": "system", "content": "你是 Story Agent 的规划助手。你只能提出建议；涉及规划变更时必须说明需要用户确认，不得声称已经直接写入正式规划。"},
            {"role": "user", "content": context},
        ]
        return {
            "providerName": provider.name,
            "modelId": model.model_id,
            "baseUrl": provider.base_url,
            "apiKey": api_key,
            "timeoutSeconds": provider.timeout_seconds,
            "maxRetries": provider.max_retries,
            "payload": {
                "model": model.model_id,
                "messages": messages,
                "temperature": model.temperature,
                "max_tokens": model.max_output_tokens,
            },
        }

    def _resolve_role_model(self, role: str) -> dict[str, Any] | None:
        self._ensure_model_role_bindings()
        with self.db.catalog() as session:
            binding = session.scalar(select(ModelRoleBinding).where(ModelRoleBinding.role == role).options(selectinload(ModelRoleBinding.model).selectinload(ModelConfig.provider)))
            if not binding or not binding.model or not binding.model.provider:
                return None
            model = binding.model
            provider = model.provider
            return {"model": self._catalog_model_snapshot(model), "provider": self._catalog_provider_snapshot(provider)}

    def _compile_agent_context(self, project_id: str, folder_path: str, session_id: str, payload: AgentMessageCreate) -> str:
        with self.db.project(project_id, folder_path) as session:
            meta = session.get(ProjectMeta, project_id)
            plan = session.scalar(select(Plan).options(selectinload(Plan.nodes), selectinload(Plan.markers)))
            agent_session = session.scalar(select(AgentSession).where(AgentSession.id == session_id).options(selectinload(AgentSession.messages)))
            node = session.get(PlanNode, payload.selected_node_id) if payload.selected_node_id else None
            recent = []
            if agent_session:
                recent = sorted(agent_session.messages, key=lambda row: row.created_at)[-12:]
            plan_summary = self._plan_dict(plan) if plan else {}
            node_summary = self._node_dict(node) if node else None
            recent_text = "\n".join(f"{message.role}: {message.content[:800]}" for message in recent)
        return (
            f"作品：{meta.title if meta else project_id}\n"
            f"模式：{meta.mode if meta else 'unknown'}\n"
            f"当前章节：{meta.current_chapter if meta else 0}/{meta.total_chapters if meta else 0}\n"
            f"用户动作：{payload.action}\n"
            f"当前规划：{json.dumps(plan_summary, ensure_ascii=False)[:6000]}\n"
            f"选中里程碑：{json.dumps(node_summary, ensure_ascii=False) if node_summary else '未选择'}\n"
            f"最近消息：\n{recent_text}\n"
            f"用户输入：{payload.content}\n"
            "请用中文回答。普通建议只输出自然语言；不要输出未确认的正式修改结果。"
        )

    def _complete_model_run_success(self, project_id: str, folder_path: str, session_id: str, run_id: str, content: str, result: Any, started: float, *, create_message: bool = True, diagnostic: dict[str, Any] | None = None) -> dict[str, Any]:
        now = utc_now()
        duration = int((time.perf_counter() - started) * 1000)
        with self.db.project(project_id, folder_path) as read_session:
            current_run = read_session.get(ModelRun, run_id)
            model_config_id = current_run.model_config_id if current_run else None
        estimated_cost = 0.0
        if model_config_id:
            with self.db.catalog() as catalog_session:
                model_config = catalog_session.get(ModelConfig, model_config_id)
                if model_config:
                    estimated_cost = (
                        ((result.prompt_tokens or 0) * (model_config.input_price_per_million or 0.0))
                        + ((result.completion_tokens or 0) * (model_config.output_price_per_million or 0.0))
                    ) / 1_000_000
        with self.db.project_write(project_id, folder_path) as session:
            run = session.get(ModelRun, run_id)
            if not run:
                raise StoryError(404, "MODEL_RUN_NOT_FOUND", "模型调用记录不存在。", {"runId": run_id})
            assistant = None
            if create_message:
                assistant = AgentMessage(id=str(uuid4()), session_id=session_id, role="assistant", content=content, created_at=now)
                session.add(assistant)
            run.status = "succeeded"
            run.prompt_tokens = result.prompt_tokens
            run.completion_tokens = result.completion_tokens
            run.total_tokens = result.total_tokens
            run.estimated_cost = estimated_cost
            run.retry_count = getattr(result, "retry_count", run.retry_count)
            run.duration_ms = duration
            if result.actual_model:
                run.model_id = result.actual_model
            if diagnostic is not None:
                run.diagnostic_json = dumps(diagnostic)
            run.ended_at = now
            agent_session = session.get(AgentSession, session_id)
            if agent_session:
                agent_session.status = "idle"
                agent_session.updated_at = now
            session.flush()
            return self._message_dict(assistant) if assistant else {}

    def _complete_model_run_failure(self, project_id: str, folder_path: str, session_id: str, run_id: str, status: str, error_code: str, started: float, *, diagnostic: dict[str, Any] | None = None, retry_count: int | None = None) -> None:
        now = utc_now()
        duration = int((time.perf_counter() - started) * 1000)
        with self.db.project_write(project_id, folder_path) as session:
            run = session.get(ModelRun, run_id)
            if run:
                was_cancel_requested = run.status == "cancel_requested"
                final_status = "cancelled" if was_cancel_requested else status
                run.status = final_status
                run.error_code = "cancelled" if final_status == "cancelled" and was_cancel_requested else error_code
                if retry_count is not None:
                    run.retry_count = retry_count
                run.duration_ms = duration
                if diagnostic is not None:
                    run.diagnostic_json = dumps(diagnostic)
                run.ended_at = now
            else:
                final_status = status
            agent_session = session.get(AgentSession, session_id)
            if agent_session:
                agent_session.status = "idle" if final_status == "cancelled" else "error"
                agent_session.updated_at = now

    def _validate_node(self, node: PlanNode) -> None:
        if node.range_min > node.range_max:
            raise StoryError(422, "INVALID_CHAPTER_RANGE", "允许范围起点不能晚于终点。")
        if node.target_chapter < node.range_min or node.target_chapter > node.range_max:
            raise StoryError(422, "TARGET_OUTSIDE_RANGE", "目标章节必须位于允许范围内。", {"targetChapter": node.target_chapter, "rangeMin": node.range_min, "rangeMax": node.range_max})
        if not loads(node.prerequisites_json) or not loads(node.completion_conditions_json):
            raise StoryError(422, "INCOMPLETE_MILESTONE_CONTRACT", "里程碑必须包含前置条件和完成条件。")
        beats = loads(node.chapter_beats_json)
        if not isinstance(beats, list):
            raise StoryError(422, "INVALID_CHAPTER_BEATS", "章节节拍必须是列表。")
        seen: set[int] = set()
        for beat in beats:
            if not isinstance(beat, dict):
                raise StoryError(422, "INVALID_CHAPTER_BEATS", "章节节拍结构无效。")
            chapter_number = beat.get("chapterNumber", beat.get("chapter_number"))
            if not isinstance(chapter_number, int) or chapter_number < node.range_min or chapter_number > node.range_max:
                raise StoryError(422, "CHAPTER_BEAT_OUTSIDE_RANGE", "章节节拍必须位于规划窗口内。", {"chapterNumber": chapter_number})
            if chapter_number in seen:
                raise StoryError(422, "DUPLICATE_CHAPTER_BEAT", "同一规划窗口不能包含重复章节节拍。", {"chapterNumber": chapter_number})
            seen.add(chapter_number)

    def _apply_proposal_operation(self, node: PlanNode, operation: ChangeOperation) -> None:
        if operation.field not in PROPOSAL_FIELD_MAP:
            raise StoryError(422, "PROPOSAL_FIELD_NOT_ALLOWED", "提案包含非白名单字段。", {"field": operation.field})
        attr, _label, value_type = PROPOSAL_FIELD_MAP[operation.field]
        raw_value = loads(operation.after_json) if operation.after_json is not None else operation.after_value
        value = self._coerce_proposal_value(operation.field, raw_value, value_type)
        if value_type == "list":
            setattr(node, attr, dumps(value))
        else:
            setattr(node, attr, value)

    def _apply_node_snapshot(self, node: PlanNode, data: dict[str, Any]) -> None:
        fields = ["title", "type", "targetChapter", "rangeMin", "rangeMax", "importance", "note", "pace"]
        mapping = {"targetChapter": "target_chapter", "rangeMin": "range_min", "rangeMax": "range_max"}
        for field in fields:
            if field in data:
                setattr(node, mapping.get(field, field), data[field])
        node.prerequisites_json = dumps(data.get("prerequisites", []))
        node.completion_conditions_json = dumps(data.get("completionConditions", []))
        node.foreshadows_json = dumps(data.get("foreshadows", []))
        node.contracts_json = dumps(data.get("contracts", []))
        node.chapter_beats_json = dumps(data.get("chapterBeats", []))

    def _audit(self, event_type: str, entity_type: str, entity_id: str, payload: dict[str, Any], request_id: str) -> AuditEvent:
        return AuditEvent(id=str(uuid4()), event_type=event_type, entity_type=entity_type, entity_id=entity_id, payload_json=dumps(payload), request_id=request_id)

    def _node_dict(self, node: PlanNode) -> dict[str, Any]:
        return {
            "id": node.id,
            "title": node.title,
            "type": node.type,
            "targetChapter": node.target_chapter,
            "rangeMin": node.range_min,
            "rangeMax": node.range_max,
            "importance": node.importance,
            "note": node.note,
            "prerequisites": loads(node.prerequisites_json),
            "completionConditions": loads(node.completion_conditions_json),
            "foreshadows": loads(node.foreshadows_json),
            "contracts": loads(node.contracts_json),
            "chapterBeats": loads(node.chapter_beats_json),
            "pace": node.pace,
            "revision": node.revision,
        }

    def _plan_dict(self, plan: Plan) -> dict[str, Any]:
        return {"id": plan.id, "bookTitle": plan.book_title, "volumeTitle": plan.volume_title, "arcTitle": plan.arc_title, "chapterStart": plan.chapter_start, "chapterEnd": plan.chapter_end, "revision": plan.revision, "milestones": [self._node_dict(node) for node in sorted(plan.nodes, key=lambda item: item.target_chapter)], "markers": [{"id": marker.id, "kind": marker.kind, "chapter": marker.chapter, "label": marker.label} for marker in sorted(plan.markers, key=lambda item: item.chapter)]}

    def _message_dict(self, item: AgentMessage) -> dict[str, Any]:
        return {"id": item.id, "role": item.role, "content": item.content, "timestamp": item.created_at}

    def _session_dict(self, item: AgentSession) -> dict[str, Any]:
        active_run = next((run for run in sorted(item.model_runs, key=lambda row: row.started_at, reverse=True) if run.status == "running"), None)
        return {"id": item.id, "projectId": item.project_id, "scope": loads(item.scope_json), "status": item.status, "messages": [self._message_dict(message) for message in sorted(item.messages, key=lambda row: row.created_at)], "activeRunId": active_run.id if active_run else None}

    def _proposal_dict(self, item: ChangeProposal | None) -> dict[str, Any]:
        assert item
        return {
            "id": item.id,
            "targetId": item.target_id,
            "targetTitle": item.target_title,
            "reason": item.reason,
            "status": item.status,
            "revision": item.revision,
            "operations": [{
                "id": op.id,
                "field": op.field,
                "label": op.label,
                "before": loads(op.before_json) if op.before_json is not None else op.before_value,
                "after": loads(op.after_json) if op.after_json is not None else op.after_value,
                "selected": op.selected,
            } for op in item.operations],
            "impacts": [{"id": impact.id, "kind": impact.kind, "label": impact.label} for impact in item.impacts],
        }

    def _audit_dict(self, item: AuditEvent) -> dict[str, Any]:
        return {"id": item.id, "eventType": item.event_type, "entityType": item.entity_type, "entityId": item.entity_id, "payload": loads(item.payload_json), "requestId": item.request_id, "createdAt": item.created_at}

    def _provider_dict(self, item: ModelProvider) -> dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "providerType": item.provider_type,
            "baseUrl": item.base_url,
            "timeoutSeconds": item.timeout_seconds,
            "maxRetries": item.max_retries,
            "isEnabled": item.is_enabled,
            "hasApiKey": bool(item.api_key_ref),
            "apiKeyPreview": item.api_key_preview,
            "lastTestStatus": item.last_test_status,
            "lastTestedAt": item.last_tested_at,
            "createdAt": item.created_at,
            "updatedAt": item.updated_at,
        }

    def _model_dict(self, item: ModelConfig) -> dict[str, Any]:
        provider_name = item.provider.name if item.provider else ""
        return {
            "id": item.id,
            "providerId": item.provider_id,
            "providerName": provider_name,
            "modelId": item.model_id,
            "displayName": item.display_name,
            "temperature": item.temperature,
            "maxOutputTokens": item.max_output_tokens,
            "supportsReasoning": item.supports_reasoning,
            "isEnabled": item.is_enabled,
            "inputPricePerMillion": item.input_price_per_million,
            "outputPricePerMillion": item.output_price_per_million,
            "createdAt": item.created_at,
            "updatedAt": item.updated_at,
        }

    def _role_binding_dict(self, item: ModelRoleBinding) -> dict[str, Any]:
        return {
            "role": item.role,
            "modelId": item.model_id,
            "model": self._model_dict(item.model) if item.model else None,
            "dailyCostLimit": item.daily_cost_limit,
            "updatedAt": item.updated_at,
        }

    def _model_run_dict(self, item: ModelRun) -> dict[str, Any]:
        return {
            "id": item.id,
            "sessionId": item.session_id,
            "role": item.role,
            "providerId": item.provider_id,
            "providerName": item.provider_name,
            "modelConfigId": item.model_config_id,
            "modelId": item.model_id,
            "automationRunId": item.automation_run_id,
            "automationRunItemId": item.automation_run_item_id,
            "status": item.status,
            "promptTokens": item.prompt_tokens,
            "completionTokens": item.completion_tokens,
            "totalTokens": item.total_tokens,
            "estimatedCost": item.estimated_cost,
            "durationMs": item.duration_ms,
            "errorCode": item.error_code,
            "diagnostic": loads(item.diagnostic_json) if item.diagnostic_json else None,
            "requestId": item.request_id,
            "retryCount": item.retry_count,
            "startedAt": item.started_at,
            "endedAt": item.ended_at,
        }

    def _catalog_provider_snapshot(self, provider: ModelProvider) -> CatalogProviderSnapshot:
        return CatalogProviderSnapshot(provider)

    def _catalog_model_snapshot(self, model: ModelConfig) -> CatalogModelSnapshot:
        return CatalogModelSnapshot(model)

    # Phase 4 delegation
    def get_canon(self, project_id: str) -> dict[str, Any]:
        return self.phase4.get_canon(project_id)

    def update_canon_draft(self, project_id: str, payload: CanonDraftUpdate) -> dict[str, Any]:
        return self.phase4.update_canon_draft(project_id, payload)

    def analyze_canon(self, project_id: str, payload: CanonAnalyzeRequest, request_id: str) -> dict[str, Any]:
        return self.phase4.analyze_canon(project_id, payload, request_id)

    def lock_canon(self, project_id: str, payload: CanonLockRequest, request_id: str) -> dict[str, Any]:
        return self.phase4.lock_canon(project_id, payload, request_id)

    def create_canon_change_request(self, project_id: str, payload: CanonChangeRequestCreate, request_id: str) -> dict[str, Any]:
        return self.phase4.create_canon_change_request(project_id, payload, request_id)

    def apply_canon_change_request(self, change_request_id: str, payload: CanonChangeRequestDecision, request_id: str) -> dict[str, Any]:
        return self.phase4.apply_canon_change_request(change_request_id, payload, request_id)

    def reject_canon_change_request(self, change_request_id: str, payload: CanonChangeRequestDecision, request_id: str) -> dict[str, Any]:
        return self.phase4.reject_canon_change_request(change_request_id, payload, request_id)

    def create_state_candidate(self, project_id: str, payload: StateCandidateCreate, request_id: str) -> dict[str, Any]:
        return self.phase4.create_state_candidate(project_id, payload, request_id)

    def commit_state_candidate(self, candidate_id: str, payload: StateCandidateCommit, request_id: str) -> dict[str, Any]:
        return self.phase4.commit_state_candidate(candidate_id, payload, request_id)

    def supersede_source_version(self, source_version_id: str, payload: SourceVersionSupersede, request_id: str) -> dict[str, Any]:
        return self.phase4.supersede_source_version(source_version_id, payload, request_id)

    def list_state_entities(self, project_id: str) -> list[dict[str, Any]]:
        return self.phase4.list_state_entities(project_id)

    def get_state_entity(self, project_id: str, entity_id: str) -> dict[str, Any]:
        return self.phase4.get_state_entity(project_id, entity_id)

    def list_foreshadows(self, project_id: str) -> list[dict[str, Any]]:
        return self.phase4.list_foreshadows(project_id)

    def list_timeline(self, project_id: str) -> list[dict[str, Any]]:
        return self.phase4.list_timeline(project_id)

    def list_snapshots(self, project_id: str) -> list[dict[str, Any]]:
        return self.phase4.list_snapshots(project_id)

    def search_retrieval(self, project_id: str, payload: RetrievalQuery) -> list[dict[str, Any]]:
        return self.phase4.search_retrieval(project_id, payload)

    def rebuild_retrieval(self, project_id: str) -> dict[str, Any]:
        return self.phase4.rebuild_retrieval(project_id)

    def retrieval_status(self, project_id: str) -> dict[str, Any]:
        return self.phase4.retrieval_status(project_id)

    def compile_context(self, project_id: str, payload: ContextCompileRequest, request_id: str) -> dict[str, Any]:
        return self.phase4.compile_context(project_id, payload, request_id)

    def get_context_trace(self, project_id: str, trace_id: str) -> dict[str, Any]:
        return self.phase4.get_context_trace(project_id, trace_id)
