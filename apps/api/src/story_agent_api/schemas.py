from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def to_camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class ProjectCreate(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    mode: Literal["long-form", "short-form", "short-drama"] = "long-form"
    total_chapters: int = Field(default=100, ge=1, le=5000)


class ProjectUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    total_chapters: int | None = Field(default=None, ge=1, le=5000)


class ProjectOut(ApiModel):
    id: str
    title: str
    mode: str
    current_chapter: int
    total_chapters: int
    folder_path: str
    created_at: datetime
    updated_at: datetime
    last_opened_at: datetime


class PlanNodeUpdate(ApiModel):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=240)
    type: str | None = None
    target_chapter: int | None = Field(default=None, ge=1, le=5000)
    range_min: int | None = Field(default=None, ge=1, le=5000)
    range_max: int | None = Field(default=None, ge=1, le=5000)
    importance: int | None = Field(default=None, ge=1, le=5)
    note: str | None = None
    prerequisites: list[str] | None = None
    completion_conditions: list[str] | None = None
    foreshadows: list[str] | None = None
    contracts: list[str] | None = None
    pace: str | None = None


class PlanNodeOut(ApiModel):
    id: str
    title: str
    type: str
    target_chapter: int
    range_min: int
    range_max: int
    importance: int
    note: str
    prerequisites: list[str]
    completion_conditions: list[str]
    foreshadows: list[str]
    contracts: list[str]
    pace: str
    revision: int


class StoryMarkerOut(ApiModel):
    id: str
    kind: str
    chapter: int
    label: str


class StoryPlanOut(ApiModel):
    id: str
    book_title: str
    volume_title: str
    arc_title: str
    chapter_start: int
    chapter_end: int
    revision: int
    milestones: list[PlanNodeOut]
    markers: list[StoryMarkerOut]


class AgentMessageOut(ApiModel):
    id: str
    role: str
    content: str
    timestamp: datetime


class AgentSessionOut(ApiModel):
    id: str
    project_id: str
    scope: list[str]
    status: str
    messages: list[AgentMessageOut]
    active_run_id: str | None = None


class AgentSessionCreate(ApiModel):
    scope: list[str] = Field(default_factory=list)


class AgentMessageCreate(ApiModel):
    project_id: str
    content: str = Field(min_length=1, max_length=5000)
    selected_node_id: str | None = None
    action: Literal["chat", "replan", "logic_check", "complete_dependencies"] = "chat"


class ChangeOperationOut(ApiModel):
    id: str
    field: str
    label: str
    before: int | str | list[str]
    after: int | str | list[str]
    selected: bool


class ImpactOut(ApiModel):
    id: str
    kind: str
    label: str


class ChangeProposalOut(ApiModel):
    id: str
    target_id: str
    target_title: str
    reason: str
    operations: list[ChangeOperationOut]
    impacts: list[ImpactOut]
    status: str
    revision: int


class AgentResponse(ApiModel):
    message: AgentMessageOut
    proposal: ChangeProposalOut | None = None
    run_id: str | None = None


class ModelRunOut(ApiModel):
    id: str
    session_id: str | None
    role: str
    provider_id: str | None
    provider_name: str
    model_config_id: str | None
    model_id: str
    status: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    duration_ms: int | None
    error_code: str | None
    diagnostic: dict[str, Any] | None = None
    request_id: str
    retry_count: int
    started_at: datetime
    ended_at: datetime | None


class ProposalApply(ApiModel):
    project_id: str
    expected_revision: int = Field(ge=1)
    selected_operation_ids: list[str] = Field(default_factory=list)


class ProposalReject(ApiModel):
    project_id: str
    expected_revision: int = Field(ge=1)


class AuditEventOut(ApiModel):
    id: str
    event_type: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    request_id: str
    created_at: datetime


class BackupManifest(ApiModel):
    backup_id: str
    project_id: str
    project_title: str
    created_at: datetime
    files: dict[str, str]
    archive_path: str


class ModelProviderCreate(ApiModel):
    name: str = Field(min_length=1, max_length=160)
    provider_type: Literal["openai-compatible"] = "openai-compatible"
    base_url: str = Field(min_length=1, max_length=1000)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_retries: int = Field(default=1, ge=0, le=5)
    is_enabled: bool = True
    api_key: str | None = Field(default=None, min_length=1, max_length=4000)


class ModelProviderUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    provider_type: Literal["openai-compatible"] | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=1000)
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    max_retries: int | None = Field(default=None, ge=0, le=5)
    is_enabled: bool | None = None
    api_key: str | None = Field(default=None, min_length=1, max_length=4000)
    clear_api_key: bool = False


class ModelConfigCreate(ApiModel):
    model_id: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_output_tokens: int = Field(default=2048, ge=1, le=200000)
    supports_reasoning: bool = False
    is_enabled: bool = True


class ModelConfigUpdate(ApiModel):
    model_id: str | None = Field(default=None, min_length=1, max_length=200)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, ge=1, le=200000)
    supports_reasoning: bool | None = None
    is_enabled: bool | None = None


class ModelProviderOut(ApiModel):
    id: str
    name: str
    provider_type: str
    base_url: str
    timeout_seconds: int
    max_retries: int
    is_enabled: bool
    has_api_key: bool
    api_key_preview: str | None = None
    created_at: datetime
    updated_at: datetime


class ModelConfigOut(ApiModel):
    id: str
    provider_id: str
    provider_name: str
    model_id: str
    display_name: str
    temperature: float
    max_output_tokens: int
    supports_reasoning: bool
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


class ModelRoleBindingOut(ApiModel):
    role: str
    model_id: str | None
    model: ModelConfigOut | None = None
    daily_cost_limit: float | None
    updated_at: datetime


class ModelRoleBindingUpdate(ApiModel):
    model_id: str | None = None
    daily_cost_limit: float | None = Field(default=None, ge=0)


class ProviderConnectionTestOut(ApiModel):
    ok: bool
    status: Literal["success", "missing_api_key", "auth_failed", "timeout", "network_error", "invalid_response", "credential_unavailable"]
    provider_id: str
    provider_name: str
    model: str | None = None
    message: str


class ApiError(ApiModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str
