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
    project_kind: Literal["demo", "standard"] = "standard"
    folder_path: str
    created_at: datetime
    updated_at: datetime
    last_opened_at: datetime


class ChapterBeat(ApiModel):
    chapter_number: int = Field(ge=1, le=5000)
    title: str = Field(min_length=1, max_length=240)
    objective: str = Field(min_length=1, max_length=2000)
    completion_conditions: list[str] = Field(default_factory=list)
    hooks: list[str] = Field(default_factory=list)
    foreshadows: list[str] = Field(default_factory=list)
    required_characters: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)


class PlanNodeCreate(ApiModel):
    title: str = Field(min_length=1, max_length=240)
    type: str = "章节窗口"
    target_chapter: int = Field(ge=1, le=5000)
    range_min: int = Field(ge=1, le=5000)
    range_max: int = Field(ge=1, le=5000)
    importance: int = Field(default=3, ge=1, le=5)
    note: str = ""
    prerequisites: list[str] = Field(default_factory=list)
    completion_conditions: list[str] = Field(default_factory=list)
    foreshadows: list[str] = Field(default_factory=list)
    contracts: list[str] = Field(default_factory=list)
    chapter_beats: list[ChapterBeat] = Field(default_factory=list)
    pace: str = "smooth"


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
    chapter_beats: list[ChapterBeat] | None = None
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
    chapter_beats: list[ChapterBeat]
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
    automation_run_id: str | None = None
    automation_run_item_id: str | None = None
    status: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    estimated_cost: float = 0.0
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


class BackupRecord(BackupManifest):
    size_bytes: int
    is_valid: bool


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
    input_price_per_million: float | None = Field(default=None, ge=0)
    output_price_per_million: float | None = Field(default=None, ge=0)


class ModelConfigUpdate(ApiModel):
    model_id: str | None = Field(default=None, min_length=1, max_length=200)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, ge=1, le=200000)
    supports_reasoning: bool | None = None
    is_enabled: bool | None = None
    input_price_per_million: float | None = Field(default=None, ge=0)
    output_price_per_million: float | None = Field(default=None, ge=0)


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
    last_test_status: str | None = None
    last_tested_at: datetime | None = None
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
    input_price_per_million: float | None = None
    output_price_per_million: float | None = None
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


class CanonDocumentOut(ApiModel):
    id: str
    title: str
    kind: str
    content_markdown: str
    status: str
    revision: int
    locked_at: datetime | None = None


class CanonEntityTypeOut(ApiModel):
    id: str
    name: str
    display_name: str
    schema_data: dict[str, Any] = Field(alias="schemaJson")
    is_system: bool
    status: str
    revision: int
    source_document_id: str | None = None
    locked_at: datetime | None = None


class CanonEntityOut(ApiModel):
    id: str
    entity_type_id: str
    canonical_name: str
    aliases: list[str]
    attributes: dict[str, Any]
    status: str
    revision: int
    source_document_id: str | None = None
    locked_at: datetime | None = None


class CanonRelationOut(ApiModel):
    id: str
    subject_entity_id: str
    predicate: str
    object_entity_id: str | None = None
    object_value: Any | None = None
    status: str
    revision: int
    source_document_id: str | None = None
    locked_at: datetime | None = None


class CanonRuleOut(ApiModel):
    id: str
    rule_code: str
    category: str
    statement: str
    severity: str
    constraint_json: dict[str, Any]
    status: str
    revision: int
    source_document_id: str | None = None
    locked_at: datetime | None = None


class CanonChangeRequestOut(ApiModel):
    id: str
    project_id: str
    target_kind: str
    target_id: str
    reason: str
    impact_summary: str
    before_json: dict[str, Any] | None = None
    after_json: dict[str, Any] | None = None
    status: str
    revision: int
    created_at: datetime
    updated_at: datetime


class CanonDraftUpdate(ApiModel):
    documents: list[dict[str, Any]] = Field(default_factory=list)
    entity_types: list[dict[str, Any]] = Field(default_factory=list)
    entities: list[dict[str, Any]] = Field(default_factory=list)
    relations: list[dict[str, Any]] = Field(default_factory=list)
    rules: list[dict[str, Any]] = Field(default_factory=list)


class CanonAnalyzeRequest(ApiModel):
    project_id: str
    source_text: str = Field(min_length=1)
    title: str | None = None


class StoryBrief(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    mode: Literal["long-form", "short-form", "short-drama"] = "long-form"
    target_chapters: int = Field(default=1000, ge=1, le=5000)
    genre: str = Field(min_length=1, max_length=200)
    premise: str = Field(min_length=20, max_length=6000)
    tone: str = Field(default="克制、悬疑、可视化", max_length=1000)
    world_preferences: list[str] = Field(default_factory=list)
    progression_preset: Literal["restrained-explicit", "strong-numeric", "rule-first"] = "restrained-explicit"
    romance: str = Field(default="弱感情线，不喧宾夺主", max_length=1000)
    forbidden_content: list[str] = Field(default_factory=list)
    reference_traits: list[str] = Field(default_factory=list)


class ArchitectureProposalDecision(ApiModel):
    expected_revision: int = Field(ge=1)


class CanonGenerationProposalOut(ApiModel):
    id: str
    project_id: str
    base_revision: int
    status: str
    brief: dict[str, Any]
    content_markdown: str
    structured: dict[str, Any]
    readiness: dict[str, Any]
    model_run_id: str | None = None
    revision: int
    created_at: datetime
    updated_at: datetime
    applied_at: datetime | None = None


class CanonReadinessOut(ApiModel):
    ready: bool
    revision: int
    checks: list[dict[str, Any]] = Field(default_factory=list)


class PlanGenerationRequest(ApiModel):
    expected_plan_revision: int = Field(ge=1)
    precise_chapter_count: Literal[5] = 5


class PlanGenerationProposalOut(ApiModel):
    id: str
    project_id: str
    base_revision: int
    status: str
    plan: dict[str, Any]
    validation: dict[str, Any]
    model_run_id: str | None = None
    revision: int
    created_at: datetime
    updated_at: datetime
    applied_at: datetime | None = None


class CanonLockRequest(ApiModel):
    expected_revision: int = Field(ge=1)


class CanonChangeRequestCreate(ApiModel):
    project_id: str
    target_kind: str
    target_id: str
    reason: str = Field(min_length=1)
    impact_summary: str = ""
    before_json: dict[str, Any] | None = None
    after_json: dict[str, Any] | None = None


class CanonChangeRequestDecision(ApiModel):
    project_id: str
    expected_revision: int = Field(ge=1)


class SourceVersionOut(ApiModel):
    id: str
    project_id: str
    source_id: str
    version_number: int
    source_kind: str
    status: str
    checksum: str
    summary: str
    revision: int
    created_at: datetime
    updated_at: datetime


class StateFactOut(ApiModel):
    id: str
    entity_id: str
    field_path: str
    value_json: Any
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    source_version_id: str | None = None
    confidence: float
    is_current: bool
    revision: int


class StoryEntityOut(ApiModel):
    id: str
    project_id: str
    entity_type_id: str
    canonical_name: str
    aliases: list[str]
    attributes: dict[str, Any]
    status: str
    revision: int
    source_document_id: str | None = None
    source_version_id: str | None = None


class StoryEventOut(ApiModel):
    id: str
    event_order: int
    occurred_at: datetime
    location: str
    participants: list[str]
    summary: str
    source_version_id: str | None = None
    revision: int


class StateDeltaOut(ApiModel):
    id: str
    event_id: str | None
    field_path: str
    before_json: Any | None = None
    after_json: Any | None = None
    source_version_id: str | None = None
    status: str
    revision: int


class ForeshadowOut(ApiModel):
    id: str
    code: str
    label: str
    description: str
    status: str
    earliest_chapter: int | None = None
    target_chapter: int | None = None
    latest_chapter: int | None = None
    source_version_id: str | None = None
    evidence: list[str]
    revision: int
    resolved_at: datetime | None = None


class KnowledgeBoundaryOut(ApiModel):
    id: str
    entity_id: str
    source_version_id: str | None = None
    knowledge_json: dict[str, Any]
    status: str
    revision: int


class StateSnapshotOut(ApiModel):
    id: str
    snapshot_number: int
    source_version_id: str | None = None
    summary_json: dict[str, Any]
    checksum: str
    revision: int
    created_at: datetime


class StateCandidateCreate(ApiModel):
    source_id: str
    version_number: int = Field(ge=1)
    source_kind: Literal["canon", "manual", "import", "chapter"] = "manual"
    summary: str = ""
    entities: list[dict[str, Any]] = Field(default_factory=list)
    facts: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    foreshadows: list[dict[str, Any]] = Field(default_factory=list)
    boundaries: list[dict[str, Any]] = Field(default_factory=list)


class StateCandidateCommit(ApiModel):
    project_id: str
    expected_revision: int = Field(ge=1)


class SourceVersionSupersede(ApiModel):
    project_id: str
    expected_revision: int = Field(ge=1)


class RetrievalQuery(ApiModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


class RetrievalHit(ApiModel):
    id: str
    kind: str
    title: str
    content: str
    source_version_id: str | None = None
    entity_id: str | None = None
    checksum: str
    score: float
    source_status: str


class RetrievalStatus(ApiModel):
    project_id: str
    indexed_count: int
    last_rebuilt_at: datetime | None = None
    vector_backend: str
    vector_available: bool
    checksum: str


class ContextCompileRequest(ApiModel):
    query: str = ""
    role: str = "planner"
    selected_node_id: str | None = None
    token_budget: int = Field(default=4000, ge=256, le=20000)


class ContextTraceItemOut(ApiModel):
    kind: str
    title: str
    source_version_id: str | None = None
    priority: int
    token_estimate: int
    reason: str
    included: bool


class ContextPackageOut(ApiModel):
    trace_id: str
    project_id: str
    role: str
    selected_node_id: str | None = None
    token_budget: int
    items: list[ContextTraceItemOut]
    payload: dict[str, Any]
    checksum: str


class ChapterContractDerive(ApiModel):
    chapter_number: int = Field(ge=1, le=5000)
    plan_node_id: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=240)
    author_note: str = ""
    target_words_min: int = Field(default=1500, ge=1, le=200000)
    target_words_max: int = Field(default=3000, ge=1, le=200000)
    pov: str = Field(default="", max_length=120)


class ChapterContractUpdate(ApiModel):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=240)
    objective: dict[str, Any] | None = None
    allowed_scope: dict[str, Any] | None = None
    forbidden_scope: dict[str, Any] | None = None
    required_characters: list[str] | None = None
    required_foreshadows: list[str] | None = None
    required_hooks: list[str] | None = None
    completion_conditions: list[str] | None = None
    pov: str | None = Field(default=None, max_length=120)
    target_words_min: int | None = Field(default=None, ge=1, le=200000)
    target_words_max: int | None = Field(default=None, ge=1, le=200000)
    pace: str | None = Field(default=None, max_length=40)


class ChapterContractLock(ApiModel):
    expected_revision: int = Field(ge=1)


class ChapterContractOut(ApiModel):
    id: str
    project_id: str
    chapter_number: int
    title: str
    plan_node_id: str | None = None
    plan_node_revision: int
    canon_revision_digest: str
    state_snapshot_id: str | None = None
    objective: dict[str, Any]
    allowed_scope: dict[str, Any]
    forbidden_scope: dict[str, Any]
    required_characters: list[str]
    required_foreshadows: list[str]
    required_hooks: list[str]
    completion_conditions: list[str]
    pov: str
    target_words_min: int
    target_words_max: int
    pace: str
    status: str
    revision: int
    created_at: datetime
    updated_at: datetime
    locked_at: datetime | None = None


class ChapterJobCreate(ApiModel):
    chapter_contract_id: str
    idempotency_key: str = Field(default="", max_length=120)


class ChapterJobRun(ApiModel):
    author_note: str = ""


class ChapterJobRetry(ApiModel):
    reason: str = ""


class ChapterQualityRevalidate(ApiModel):
    """Request a deterministic quality pass against the current candidate.

    This is intentionally separate from a revision: it is for safely
    re-evaluating an existing draft after a deterministic-rule upgrade, and
    must never invoke a writer or mutate the candidate body.
    """

    expected_job_revision: int = Field(ge=1)


class ChapterJobOut(ApiModel):
    id: str
    project_id: str
    chapter_contract_id: str
    status: str
    attempt_number: int
    current_revision_round: int
    context_trace_id: str | None = None
    idempotency_key: str
    error_code: str | None = None
    diagnostic: dict[str, Any] | None = None
    revision: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime
    contract: ChapterContractOut | None = None


class ChapterDraftOut(ApiModel):
    id: str
    project_id: str
    chapter_job_id: str
    chapter_contract_id: str
    version_number: int
    parent_draft_id: str | None = None
    kind: str
    content_markdown: str
    word_count: int
    checksum: str
    model_run_id: str | None = None
    context_trace_id: str | None = None
    status: str
    is_current: bool
    revision: int
    created_at: datetime
    updated_at: datetime


class ChapterExtractionOut(ApiModel):
    id: str
    project_id: str
    chapter_draft_id: str
    model_run_id: str | None = None
    payload: dict[str, Any]
    schema_version: int
    status: str
    validation_errors: list[dict[str, Any]]
    checksum: str
    created_at: datetime
    updated_at: datetime


class QualityFindingOut(ApiModel):
    id: str
    project_id: str
    quality_run_id: str
    chapter_draft_id: str
    rule_code: str
    severity: str
    category: str
    message: str
    evidence: list[Any]
    location: dict[str, Any]
    suggested_fix: str
    fingerprint: str
    status: str
    accepted_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class QualityRunOut(ApiModel):
    id: str
    project_id: str
    chapter_job_id: str
    chapter_draft_id: str
    gate_type: str
    reviewer_role: str | None = None
    model_run_id: str | None = None
    status: str
    summary: dict[str, Any]
    created_at: datetime
    completed_at: datetime | None = None
    findings: list[QualityFindingOut] = Field(default_factory=list)


class QualityReportOut(ApiModel):
    job_id: str
    current_draft_id: str | None = None
    open_blocking_count: int
    runs: list[QualityRunOut]
    findings: list[QualityFindingOut]


class QualityFindingAcceptRisk(ApiModel):
    reason: str = Field(min_length=1, max_length=2000)


class ChapterRevisionRequest(ApiModel):
    reason: str = ""


class ChapterManualRevisionRequest(ApiModel):
    content_markdown: str = Field(min_length=1, max_length=1000000)
    reason: str = Field(default="", max_length=2000)
    parent_draft_id: str
    expected_parent_revision: int = Field(ge=1)
    expected_job_revision: int = Field(ge=1)


class ChapterDraftActivateRequest(ApiModel):
    expected_draft_revision: int = Field(ge=1)
    expected_job_revision: int = Field(ge=1)


class ChapterApproveRequest(ApiModel):
    mode: Literal["manual", "guarded_auto"] = "manual"
    expected_job_revision: int = Field(ge=1)


class ChapterCommitRequest(ApiModel):
    expected_job_revision: int = Field(ge=1)


class ChapterCommitOut(ApiModel):
    id: str
    project_id: str
    chapter_number: int
    chapter_contract_id: str
    approved_draft_id: str
    source_version_id: str
    state_snapshot_id: str | None = None
    quality_summary: dict[str, Any]
    checksum: str
    status: str
    is_current: bool
    revision: int
    committed_at: datetime
    created_at: datetime


class ExportProfileUpdate(ApiModel):
    expected_revision: int = Field(ge=1)
    default_formats: list[Literal["txt", "markdown", "docx", "epub"]] | None = None
    book_title: str | None = Field(default=None, max_length=240)
    author_name: str | None = Field(default=None, max_length=160)
    description: str | None = None
    chapter_title_template: str | None = Field(default=None, min_length=1, max_length=160)
    include_quality_summary: bool | None = None


class ExportProfileOut(ApiModel):
    project_id: str
    default_formats: list[str]
    book_title: str
    author_name: str
    description: str
    chapter_title_template: str
    include_quality_summary: bool
    revision: int
    created_at: datetime
    updated_at: datetime


class ExportReadinessRequest(ApiModel):
    mode: Literal["formal", "review"] = "formal"
    chapter_start: int = Field(ge=1, le=5000)
    chapter_end: int = Field(ge=1, le=5000)
    formats: list[Literal["txt", "markdown", "docx", "epub"]] | None = None


class ExportIssue(ApiModel):
    code: str
    severity: Literal["blocker", "warning"] = "blocker"
    chapter_number: int | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    suggestion: str = ""


class ExportReadinessOut(ApiModel):
    ready: bool
    mode: str
    chapter_start: int
    chapter_end: int
    exportable_chapter_count: int
    formats: list[str]
    estimated_file_names: dict[str, str]
    issues: list[ExportIssue] = Field(default_factory=list)


class ExportCreate(ApiModel):
    mode: Literal["formal", "review"] = "formal"
    chapter_start: int = Field(ge=1, le=5000)
    chapter_end: int = Field(ge=1, le=5000)
    formats: list[Literal["txt", "markdown", "docx", "epub"]] | None = None
    idempotency_key: str | None = Field(default=None, max_length=120)


class ExportArtifactOut(ApiModel):
    id: str
    project_id: str
    export_job_id: str
    format: str
    file_name: str
    mime_type: str
    byte_size: int
    sha256: str
    status: str
    is_current: bool
    revision: int
    created_at: datetime
    updated_at: datetime


class ExportJobChapterOut(ApiModel):
    id: str
    project_id: str
    export_job_id: str
    chapter_number: int
    sequence_number: int
    chapter_title: str
    chapter_commit_id: str | None = None
    approved_draft_id: str | None = None
    source_version_id: str | None = None
    state_snapshot_id: str | None = None
    commit_revision: int | None = None
    source_revision: int | None = None
    draft_revision: int | None = None
    snapshot_revision: int | None = None
    commit_checksum: str
    draft_checksum: str
    source_checksum: str
    quality_summary: dict[str, Any]
    issue_summary: list[dict[str, Any]]
    missing: bool
    created_at: datetime
    updated_at: datetime


class ExportJobOut(ApiModel):
    id: str
    project_id: str
    mode: str
    chapter_start: int
    chapter_end: int
    formats: list[str]
    idempotency_key: str | None = None
    status: str
    frozen_manifest: dict[str, Any]
    readiness: dict[str, Any]
    stop_reason: str | None = None
    diagnostic: dict[str, Any] | None = None
    revision: int
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime
    chapters: list[ExportJobChapterOut] = Field(default_factory=list)
    artifacts: list[ExportArtifactOut] = Field(default_factory=list)


class PublicationRecordCreate(ApiModel):
    artifact_id: str
    platform: str = Field(min_length=1, max_length=120)
    external_work_ref: str = Field(default="", max_length=240)
    external_chapter_ref: str = Field(default="", max_length=240)
    published_at: datetime | None = None
    notes: str = ""


class PublicationRecordOut(ApiModel):
    id: str
    project_id: str
    export_job_id: str
    artifact_id: str
    platform: str
    external_work_ref: str
    external_chapter_ref: str
    published_at: datetime
    notes: str
    revision: int
    created_at: datetime
    updated_at: datetime


class AutomationPolicyUpdate(ApiModel):
    expected_revision: int = Field(ge=1)
    enabled: bool
    time_of_day: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str = Field(min_length=1, max_length=80)
    chapters_per_run: int = Field(ge=1, le=10)
    target_words_min: int = Field(ge=1, le=200000)
    target_words_max: int = Field(ge=1, le=200000)
    max_revision_rounds: int = Field(ge=0, le=2)
    daily_cost_limit: float | None = Field(default=None, ge=0)
    stop_policy: Literal["stop_on_blocking", "stop_on_any_failure"] = "stop_on_blocking"
    approval_mode: Literal["guarded_auto"] = "guarded_auto"


class AutomationPolicyOut(ApiModel):
    project_id: str
    enabled: bool
    time_of_day: str
    timezone: str
    chapters_per_run: int
    target_words_min: int
    target_words_max: int
    max_revision_rounds: int
    daily_cost_limit: float | None = None
    stop_policy: str
    approval_mode: str
    next_run_at: datetime | None = None
    last_scheduled_local_date: str | None = None
    revision: int
    created_at: datetime
    updated_at: datetime


class AutomationRunCreate(ApiModel):
    idempotency_key: str | None = Field(default=None, max_length=120)
    chapter_count: Literal[1, 3, 5] | None = None


class AutomationRunItemOut(ApiModel):
    id: str
    project_id: str
    automation_run_id: str
    chapter_number: int
    sequence_number: int
    chapter_contract_id: str | None = None
    chapter_job_id: str | None = None
    chapter_commit_id: str | None = None
    status: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float
    error_code: str | None = None
    diagnostic: dict[str, Any] | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime


class AutomationRunOut(ApiModel):
    id: str
    project_id: str
    policy_id: str
    scheduled_local_date: str
    trigger: str
    status: str
    idempotency_key: str | None = None
    requested_chapter_count: int | None = None
    start_chapter: int | None = None
    end_chapter: int | None = None
    planned_count: int
    succeeded_count: int
    isolated_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float
    stop_reason: str | None = None
    diagnostic: dict[str, Any] | None = None
    revision: int
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime
    items: list[AutomationRunItemOut] = Field(default_factory=list)
    available_actions: list[str] = Field(default_factory=list)
    next_run_at: datetime | None = None


class AutomationDailyReportOut(ApiModel):
    id: str
    project_id: str
    local_date: str
    timezone: str
    run_count: int
    planned_count: int
    succeeded_count: int
    isolated_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float
    status_summary: dict[str, int]
    generated_at: datetime
    updated_at: datetime


class TrialReadinessCheckOut(ApiModel):
    code: str
    status: Literal["ready", "warning", "blocked"]
    title: str
    detail: str
    action_path: str | None = None
    chapter_number: int | None = None


class TrialReadinessOut(ApiModel):
    project_id: str
    chapter_count: Literal[1, 3, 5]
    start_chapter: int
    end_chapter: int
    ready: bool
    max_safe_chapter_count: int
    checks: list[TrialReadinessCheckOut]


class EnduranceReadinessCheckOut(ApiModel):
    code: str
    status: Literal["ready", "warning", "blocked"]
    title: str
    detail: str
    chapter_number: int | None = None


class EnduranceReadinessOut(ApiModel):
    project_id: str
    chapter_count: Literal[5, 10, 20, 30]
    start_chapter: int
    end_chapter: int
    ready: bool
    max_safe_chapter_count: int
    checks: list[EnduranceReadinessCheckOut]
    updated_at: datetime


class EnduranceSuiteCreate(ApiModel):
    name: str = Field(default="Longform endurance", min_length=1, max_length=160)
    start_chapter: int | None = Field(default=None, ge=1, le=5000)
    target_chapter_count: Literal[5, 10, 20, 30] = 5
    daily_cost_limit: float | None = Field(default=None, ge=0)
    total_cost_limit: float | None = Field(default=None, ge=0)
    consecutive_failure_limit: int = Field(default=2, ge=1, le=10)
    stop_severity: Literal["error", "blocker"] = "blocker"
    enabled_rules: list[str] = Field(default_factory=list)


class EnduranceSuiteUpdate(ApiModel):
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    target_chapter_count: Literal[5, 10, 20, 30] | None = None
    daily_cost_limit: float | None = Field(default=None, ge=0)
    total_cost_limit: float | None = Field(default=None, ge=0)
    consecutive_failure_limit: int | None = Field(default=None, ge=1, le=10)
    stop_severity: Literal["error", "blocker"] | None = None
    enabled_rules: list[str] | None = None


class EnduranceSuiteOut(ApiModel):
    id: str
    project_id: str
    name: str
    start_chapter: int
    target_chapter_count: int
    daily_cost_limit: float | None = None
    total_cost_limit: float | None = None
    consecutive_failure_limit: int
    stop_severity: str
    enabled_rules: list[str]
    revision: int
    created_at: datetime
    updated_at: datetime


class EnduranceRunCreate(ApiModel):
    suite_id: str
    idempotency_key: str | None = Field(default=None, max_length=120)
    chapter_count: Literal[5, 10, 20, 30] | None = None


class EnduranceRunAction(ApiModel):
    expected_revision: int = Field(ge=1)


class EnduranceCheckpointOut(ApiModel):
    id: str
    project_id: str
    run_id: str
    automation_run_id: str | None = None
    automation_run_item_id: str | None = None
    chapter_number: int
    chapter_commit_id: str
    source_version_id: str
    state_snapshot_id: str
    commit_revision: int
    source_revision: int
    snapshot_revision: int
    commit_checksum: str
    source_checksum: str
    snapshot_checksum: str
    canon_revision: int
    plan_revision: int
    budget_summary: dict[str, Any]
    character_knowledge: dict[str, Any]
    ability_summary: dict[str, Any]
    item_summary: dict[str, Any]
    foreshadow_summary: dict[str, Any]
    cost_summary: dict[str, Any]
    checkpoint_checksum: str
    validation_status: str
    created_at: datetime


class EnduranceFindingOut(ApiModel):
    id: str
    project_id: str
    run_id: str
    checkpoint_id: str | None = None
    rule_code: str
    severity: str
    chapter_number: int | None = None
    evidence: dict[str, Any]
    suggestion: str
    status: str
    fingerprint: str
    revision: int
    created_at: datetime
    updated_at: datetime


class EnduranceReportOut(ApiModel):
    id: str
    project_id: str
    run_id: str
    success_count: int
    isolated_count: int
    failed_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float
    average_revision_rounds: float
    quality_trend: dict[str, Any]
    drift_trend: dict[str, Any]
    stop_reason: str | None = None
    checksum: str
    generated_at: datetime
    updated_at: datetime


class EnduranceRunOut(ApiModel):
    id: str
    project_id: str
    suite_id: str
    status: str
    idempotency_key: str | None = None
    start_chapter: int
    end_chapter: int
    target_chapter_count: int
    completed_count: int
    current_automation_run_id: str | None = None
    current_automation_run_item_id: str | None = None
    last_checkpoint_id: str | None = None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float
    stop_reason: str | None = None
    diagnostic: dict[str, Any] | None = None
    revision: int
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime
    checkpoints: list[EnduranceCheckpointOut] = Field(default_factory=list)
    findings: list[EnduranceFindingOut] = Field(default_factory=list)
    report: EnduranceReportOut | None = None
    available_actions: list[str] = Field(default_factory=list)
