from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CatalogBase(DeclarativeBase):
    pass


class ProjectBase(DeclarativeBase):
    pass


class CatalogProject(CatalogBase):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(200))
    mode: Mapped[str] = mapped_column(String(40))
    folder_path: Mapped[str] = mapped_column(Text, unique=True)
    current_chapter: Mapped[int] = mapped_column(Integer, default=0)
    total_chapters: Mapped[int] = mapped_column(Integer, default=100)
    project_kind: Mapped[str] = mapped_column(String(20), default="standard", index=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AppSetting(CatalogBase):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class ModelProvider(CatalogBase):
    __tablename__ = "model_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    provider_type: Mapped[str] = mapped_column(String(60), default="openai-compatible")
    base_url: Mapped[str] = mapped_column(Text)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    max_retries: Mapped[int] = mapped_column(Integer, default=1)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    api_key_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    api_key_preview: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_test_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    models: Mapped[list[ModelConfig]] = relationship(back_populates="provider", cascade="all, delete-orphan")


class ModelConfig(CatalogBase):
    __tablename__ = "model_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("model_providers.id", ondelete="RESTRICT"), index=True)
    model_id: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(200))
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=2048)
    supports_reasoning: Mapped[bool] = mapped_column(Boolean, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    input_price_per_million: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_price_per_million: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    provider: Mapped[ModelProvider] = relationship(back_populates="models")
    role_bindings: Mapped[list[ModelRoleBinding]] = relationship(back_populates="model")


class ModelRoleBinding(CatalogBase):
    __tablename__ = "model_role_bindings"

    role: Mapped[str] = mapped_column(String(80), primary_key=True)
    model_id: Mapped[str | None] = mapped_column(ForeignKey("model_configs.id", ondelete="SET NULL"), nullable=True, index=True)
    daily_cost_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    model: Mapped[ModelConfig | None] = relationship(back_populates="role_bindings")


class ProjectMeta(ProjectBase):
    __tablename__ = "project_meta"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    mode: Mapped[str] = mapped_column(String(40))
    current_chapter: Mapped[int] = mapped_column(Integer, default=0)
    total_chapters: Mapped[int] = mapped_column(Integer, default=100)
    project_kind: Mapped[str] = mapped_column(String(20), default="standard", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Plan(ProjectBase):
    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    book_title: Mapped[str] = mapped_column(String(200))
    volume_title: Mapped[str] = mapped_column(String(200))
    arc_title: Mapped[str] = mapped_column(String(200))
    chapter_start: Mapped[int] = mapped_column(Integer, default=1)
    chapter_end: Mapped[int] = mapped_column(Integer, default=100)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    nodes: Mapped[list[PlanNode]] = relationship(back_populates="plan", cascade="all, delete-orphan")
    markers: Mapped[list[StoryMarker]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class PlanNode(ProjectBase):
    __tablename__ = "plan_nodes"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    type: Mapped[str] = mapped_column(String(40))
    target_chapter: Mapped[int] = mapped_column(Integer)
    range_min: Mapped[int] = mapped_column(Integer)
    range_max: Mapped[int] = mapped_column(Integer)
    importance: Mapped[int] = mapped_column(Integer, default=3)
    note: Mapped[str] = mapped_column(Text, default="")
    prerequisites_json: Mapped[str] = mapped_column(Text, default="[]")
    completion_conditions_json: Mapped[str] = mapped_column(Text, default="[]")
    foreshadows_json: Mapped[str] = mapped_column(Text, default="[]")
    contracts_json: Mapped[str] = mapped_column(Text, default="[]")
    chapter_beats_json: Mapped[str] = mapped_column(Text, default="[]")
    pace: Mapped[str] = mapped_column(String(20), default="smooth")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    plan: Mapped[Plan] = relationship(back_populates="nodes")


class StoryMarker(ProjectBase):
    __tablename__ = "story_markers"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    chapter: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(200))
    plan: Mapped[Plan] = relationship(back_populates="markers")


class AgentSession(ProjectBase):
    __tablename__ = "agent_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    scope_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(20), default="idle")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    messages: Mapped[list[AgentMessage]] = relationship(back_populates="session", cascade="all, delete-orphan")
    model_runs: Mapped[list[ModelRun]] = relationship(back_populates="session")


class AgentMessage(ProjectBase):
    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    session: Mapped[AgentSession] = relationship(back_populates="messages")


class ModelRun(ProjectBase):
    __tablename__ = "model_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("agent_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(80), index=True)
    provider_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider_name: Mapped[str] = mapped_column(String(160), default="")
    model_config_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    model_id: Mapped[str] = mapped_column(String(200), default="")
    automation_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    automation_run_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    diagnostic_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str] = mapped_column(String(36), index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    session: Mapped[AgentSession | None] = relationship(back_populates="model_runs")


class ChangeProposal(ProjectBase):
    __tablename__ = "change_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(60), index=True)
    target_title: Mapped[str] = mapped_column(String(240))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    operations: Mapped[list[ChangeOperation]] = relationship(back_populates="proposal", cascade="all, delete-orphan")
    impacts: Mapped[list[ProposalImpact]] = relationship(back_populates="proposal", cascade="all, delete-orphan")


class ChangeOperation(ProjectBase):
    __tablename__ = "change_operations"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("change_proposals.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(String(120))
    before_value: Mapped[int] = mapped_column(Integer)
    after_value: Mapped[int] = mapped_column(Integer)
    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected: Mapped[bool] = mapped_column(Boolean, default=True)
    proposal: Mapped[ChangeProposal] = relationship(back_populates="operations")


class ProposalImpact(ProjectBase):
    __tablename__ = "proposal_impacts"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("change_proposals.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(200))
    proposal: Mapped[ChangeProposal] = relationship(back_populates="impacts")


class AuditEvent(ProjectBase):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(80), index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    request_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CanonDocument(ProjectBase):
    __tablename__ = "canon_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(240))
    kind: Mapped[str] = mapped_column(String(60), index=True)
    content_markdown: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CanonEntityType(ProjectBase):
    __tablename__ = "canon_entity_types"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    schema_json: Mapped[str] = mapped_column(Text, default="{}")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    source_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CanonEntity(ProjectBase):
    __tablename__ = "canon_entities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_type_id: Mapped[str] = mapped_column(String(36), index=True)
    canonical_name: Mapped[str] = mapped_column(String(240), unique=True, index=True)
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    attributes_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    source_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CanonRelation(ProjectBase):
    __tablename__ = "canon_relations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject_entity_id: Mapped[str] = mapped_column(String(36), index=True)
    predicate: Mapped[str] = mapped_column(String(120), index=True)
    object_entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    object_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    source_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CanonRule(ProjectBase):
    __tablename__ = "canon_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    rule_code: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    statement: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20), default="medium", index=True)
    constraint_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    source_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CanonGenerationProposal(ProjectBase):
    __tablename__ = "canon_generation_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    base_revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    brief_json: Mapped[str] = mapped_column(Text, default="{}")
    content_markdown: Mapped[str] = mapped_column(Text, default="")
    structured_json: Mapped[str] = mapped_column(Text, default="{}")
    readiness_json: Mapped[str] = mapped_column(Text, default="{}")
    model_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlanGenerationProposal(ProjectBase):
    __tablename__ = "plan_generation_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    base_revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    plan_json: Mapped[str] = mapped_column(Text, default="{}")
    validation_json: Mapped[str] = mapped_column(Text, default="{}")
    model_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StoryBudget(ProjectBase):
    __tablename__ = "story_budgets"
    __table_args__ = (Index("uq_story_budgets_project_code", "project_id", "code", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(240))
    earliest_chapter: Mapped[int] = mapped_column(Integer)
    target_min: Mapped[int] = mapped_column(Integer)
    target_max: Mapped[int] = mapped_column(Integer)
    latest_chapter: Mapped[int] = mapped_column(Integer)
    prerequisites_json: Mapped[str] = mapped_column(Text, default="[]")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="planned", index=True)
    consumed_chapter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CanonChangeRequest(ProjectBase):
    __tablename__ = "canon_change_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    target_kind: Mapped[str] = mapped_column(String(40), index=True)
    target_id: Mapped[str] = mapped_column(String(36), index=True)
    reason: Mapped[str] = mapped_column(Text)
    impact_summary: Mapped[str] = mapped_column(Text, default="")
    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SourceVersion(ProjectBase):
    __tablename__ = "source_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    source_id: Mapped[str] = mapped_column(String(120), index=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    source_kind: Mapped[str] = mapped_column(String(40), default="manual", index=True)
    status: Mapped[str] = mapped_column(String(20), default="candidate", index=True)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class StoryEntity(ProjectBase):
    __tablename__ = "story_entities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    entity_type_id: Mapped[str] = mapped_column(String(36), index=True)
    canonical_name: Mapped[str] = mapped_column(String(240), unique=True, index=True)
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    attributes_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    source_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    source_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class StateFact(ProjectBase):
    __tablename__ = "state_facts"
    __table_args__ = (
        Index(
            "uq_state_facts_current",
            "project_id",
            "entity_id",
            "field_path",
            unique=True,
            sqlite_where=text("is_current = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    field_path: Mapped[str] = mapped_column(String(240), index=True)
    value_json: Mapped[str] = mapped_column(Text, default="null")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class StoryEvent(ProjectBase):
    __tablename__ = "story_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    event_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    location: Mapped[str] = mapped_column(String(200), default="")
    participants_json: Mapped[str] = mapped_column(Text, default="[]")
    summary: Mapped[str] = mapped_column(Text, default="")
    source_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class StateDelta(ProjectBase):
    __tablename__ = "state_deltas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    event_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    field_path: Mapped[str] = mapped_column(String(240), index=True)
    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="official", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Foreshadow(ProjectBase):
    __tablename__ = "foreshadows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(120), index=True)
    label: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    earliest_chapter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_chapter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latest_chapter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeBoundary(ProjectBase):
    __tablename__ = "knowledge_boundaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    source_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    knowledge_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class StateSnapshot(ProjectBase):
    __tablename__ = "state_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    snapshot_number: Mapped[int] = mapped_column(Integer, default=1, index=True)
    source_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    checksum: Mapped[str] = mapped_column(String(64), default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RetrievalIndexState(ProjectBase):
    __tablename__ = "retrieval_index_state"

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    last_rebuilt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    indexed_count: Mapped[int] = mapped_column(Integer, default=0)
    vector_backend: Mapped[str] = mapped_column(String(60), default="sqlite-local")
    vector_available: Mapped[bool] = mapped_column(Boolean, default=True)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ContextTrace(ProjectBase):
    __tablename__ = "context_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(80), index=True)
    query: Mapped[str] = mapped_column(Text, default="")
    selected_node_id: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    token_budget: Mapped[int] = mapped_column(Integer, default=4000)
    package_json: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ChapterContract(ProjectBase):
    __tablename__ = "chapter_contracts"
    __table_args__ = (
        Index(
            "uq_chapter_contracts_locked",
            "project_id",
            "chapter_number",
            unique=True,
            sqlite_where=text("status = 'locked'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    chapter_number: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(240))
    plan_node_id: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    plan_node_revision: Mapped[int] = mapped_column(Integer, default=1)
    canon_revision_digest: Mapped[str] = mapped_column(String(64), default="")
    state_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    objective_json: Mapped[str] = mapped_column(Text, default="{}")
    allowed_scope_json: Mapped[str] = mapped_column(Text, default="{}")
    forbidden_scope_json: Mapped[str] = mapped_column(Text, default="{}")
    required_characters_json: Mapped[str] = mapped_column(Text, default="[]")
    required_foreshadows_json: Mapped[str] = mapped_column(Text, default="[]")
    required_hooks_json: Mapped[str] = mapped_column(Text, default="[]")
    completion_conditions_json: Mapped[str] = mapped_column(Text, default="[]")
    pov: Mapped[str] = mapped_column(String(120), default="")
    target_words_min: Mapped[int] = mapped_column(Integer, default=1500)
    target_words_max: Mapped[int] = mapped_column(Integer, default=3000)
    pace: Mapped[str] = mapped_column(String(40), default="smooth")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChapterJob(ProjectBase):
    __tablename__ = "chapter_jobs"
    __table_args__ = (
        Index(
            "uq_chapter_jobs_idempotency",
            "project_id",
            "chapter_contract_id",
            "idempotency_key",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    chapter_contract_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    current_revision_round: Mapped[int] = mapped_column(Integer, default=0)
    context_trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), default="")
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    diagnostic_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ChapterDraft(ProjectBase):
    __tablename__ = "chapter_drafts"
    __table_args__ = (
        Index("uq_chapter_drafts_job_version", "chapter_job_id", "version_number", unique=True),
        Index(
            "uq_chapter_drafts_current",
            "chapter_job_id",
            unique=True,
            sqlite_where=text("is_current = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    chapter_job_id: Mapped[str] = mapped_column(String(36), index=True)
    chapter_contract_id: Mapped[str] = mapped_column(String(36), index=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    parent_draft_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), default="generated", index=True)
    content_markdown: Mapped[str] = mapped_column(Text, default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    model_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    context_trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="candidate", index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ChapterExtraction(ProjectBase):
    __tablename__ = "chapter_extractions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    chapter_draft_id: Mapped[str] = mapped_column(String(36), index=True)
    model_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="candidate", index=True)
    validation_errors_json: Mapped[str] = mapped_column(Text, default="[]")
    checksum: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class QualityRun(ProjectBase):
    __tablename__ = "quality_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    chapter_job_id: Mapped[str] = mapped_column(String(36), index=True)
    chapter_draft_id: Mapped[str] = mapped_column(String(36), index=True)
    gate_type: Mapped[str] = mapped_column(String(30), index=True)
    reviewer_role: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    model_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QualityFinding(ProjectBase):
    __tablename__ = "quality_findings"
    __table_args__ = (
        Index("uq_quality_findings_draft_fingerprint", "chapter_draft_id", "fingerprint", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    quality_run_id: Mapped[str] = mapped_column(String(36), index=True)
    chapter_draft_id: Mapped[str] = mapped_column(String(36), index=True)
    rule_code: Mapped[str] = mapped_column(String(120), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    message: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    location_json: Mapped[str] = mapped_column(Text, default="{}")
    suggested_fix: Mapped[str] = mapped_column(Text, default="")
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    accepted_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ChapterCommit(ProjectBase):
    __tablename__ = "chapter_commits"
    __table_args__ = (
        Index(
            "uq_chapter_commits_current",
            "project_id",
            "chapter_number",
            unique=True,
            sqlite_where=text("is_current = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    chapter_number: Mapped[int] = mapped_column(Integer, index=True)
    chapter_contract_id: Mapped[str] = mapped_column(String(36), index=True)
    approved_draft_id: Mapped[str] = mapped_column(String(36), index=True)
    source_version_id: Mapped[str] = mapped_column(String(36), index=True)
    state_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    quality_summary_json: Mapped[str] = mapped_column(Text, default="{}")
    checksum: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(20), default="official", index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ExportProfile(ProjectBase):
    __tablename__ = "export_profiles"

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    default_formats_json: Mapped[str] = mapped_column(Text, default='["txt","markdown","docx","epub"]')
    book_title: Mapped[str] = mapped_column(String(240), default="")
    author_name: Mapped[str] = mapped_column(String(160), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    chapter_title_template: Mapped[str] = mapped_column(String(160), default="第{chapter}章 {title}")
    include_quality_summary: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ExportJob(ProjectBase):
    __tablename__ = "export_jobs"
    __table_args__ = (
        Index(
            "uq_export_jobs_idempotency",
            "project_id",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL AND idempotency_key != ''"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    mode: Mapped[str] = mapped_column(String(20), default="formal", index=True)
    chapter_start: Mapped[int] = mapped_column(Integer)
    chapter_end: Mapped[int] = mapped_column(Integer)
    formats_json: Mapped[str] = mapped_column(Text, default="[]")
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    frozen_manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    readiness_json: Mapped[str] = mapped_column(Text, default="{}")
    stop_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    diagnostic_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ExportJobChapter(ProjectBase):
    __tablename__ = "export_job_chapters"
    __table_args__ = (Index("uq_export_job_chapters_job_chapter", "export_job_id", "chapter_number", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    export_job_id: Mapped[str] = mapped_column(String(36), index=True)
    chapter_number: Mapped[int] = mapped_column(Integer, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer)
    chapter_title: Mapped[str] = mapped_column(String(240), default="")
    chapter_commit_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    approved_draft_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    source_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    state_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    commit_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    draft_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    commit_checksum: Mapped[str] = mapped_column(String(64), default="")
    draft_checksum: Mapped[str] = mapped_column(String(64), default="")
    source_checksum: Mapped[str] = mapped_column(String(64), default="")
    quality_summary_json: Mapped[str] = mapped_column(Text, default="{}")
    issue_summary_json: Mapped[str] = mapped_column(Text, default="[]")
    content_markdown: Mapped[str] = mapped_column(Text, default="")
    missing: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ExportArtifact(ProjectBase):
    __tablename__ = "export_artifacts"
    __table_args__ = (
        Index(
            "uq_export_artifacts_current",
            "export_job_id",
            "format",
            unique=True,
            sqlite_where=text("is_current = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    export_job_id: Mapped[str] = mapped_column(String(36), index=True)
    format: Mapped[str] = mapped_column(String(20), index=True)
    relative_path: Mapped[str] = mapped_column(Text, default="")
    mime_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    file_name: Mapped[str] = mapped_column(String(240), default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="available", index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PublicationRecord(ProjectBase):
    __tablename__ = "publication_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    export_job_id: Mapped[str] = mapped_column(String(36), index=True)
    artifact_id: Mapped[str] = mapped_column(String(36), index=True)
    platform: Mapped[str] = mapped_column(String(120), index=True)
    external_work_ref: Mapped[str] = mapped_column(String(240), default="")
    external_chapter_ref: Mapped[str] = mapped_column(String(240), default="")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    notes: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AutomationPolicy(ProjectBase):
    __tablename__ = "automation_policies"

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    time_of_day: Mapped[str] = mapped_column(String(5), default="03:00")
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    chapters_per_run: Mapped[int] = mapped_column(Integer, default=1)
    target_words_min: Mapped[int] = mapped_column(Integer, default=1500)
    target_words_max: Mapped[int] = mapped_column(Integer, default=3000)
    max_revision_rounds: Mapped[int] = mapped_column(Integer, default=2)
    daily_cost_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_policy: Mapped[str] = mapped_column(String(40), default="stop_on_blocking")
    approval_mode: Mapped[str] = mapped_column(String(40), default="guarded_auto")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_scheduled_local_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AutomationRun(ProjectBase):
    __tablename__ = "automation_runs"
    __table_args__ = (
        Index(
            "uq_automation_runs_scheduled_date",
            "project_id",
            "scheduled_local_date",
            unique=True,
            sqlite_where=text("trigger = 'scheduled'"),
        ),
        Index(
            "uq_automation_runs_idempotency",
            "project_id",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL AND idempotency_key != ''"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    policy_id: Mapped[str] = mapped_column(String(36), index=True)
    scheduled_local_date: Mapped[str] = mapped_column(String(10), index=True)
    trigger: Mapped[str] = mapped_column(String(20), default="manual", index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    requested_chapter_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_chapter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_chapter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    planned_count: Mapped[int] = mapped_column(Integer, default=0)
    succeeded_count: Mapped[int] = mapped_column(Integer, default=0)
    isolated_count: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    stop_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    diagnostic_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AutomationRunItem(ProjectBase):
    __tablename__ = "automation_run_items"
    __table_args__ = (
        Index("uq_automation_run_items_chapter", "automation_run_id", "chapter_number", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    automation_run_id: Mapped[str] = mapped_column(String(36), index=True)
    chapter_number: Mapped[int] = mapped_column(Integer, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer)
    chapter_contract_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    chapter_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    chapter_commit_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="waiting", index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    diagnostic_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AutomationLease(ProjectBase):
    __tablename__ = "automation_leases"

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(120), index=True)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class AutomationDailyReport(ProjectBase):
    __tablename__ = "automation_daily_reports"
    __table_args__ = (
        Index("uq_automation_daily_reports_date", "project_id", "local_date", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    local_date: Mapped[str] = mapped_column(String(10), index=True)
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    planned_count: Mapped[int] = mapped_column(Integer, default=0)
    succeeded_count: Mapped[int] = mapped_column(Integer, default=0)
    isolated_count: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    status_summary_json: Mapped[str] = mapped_column(Text, default="{}")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class EnduranceSuite(ProjectBase):
    __tablename__ = "endurance_suites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(160))
    start_chapter: Mapped[int] = mapped_column(Integer, default=1)
    target_chapter_count: Mapped[int] = mapped_column(Integer, default=5)
    daily_cost_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_cost_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    consecutive_failure_limit: Mapped[int] = mapped_column(Integer, default=2)
    stop_severity: Mapped[str] = mapped_column(String(20), default="blocker")
    enabled_rules_json: Mapped[str] = mapped_column(Text, default="[]")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class EnduranceRun(ProjectBase):
    __tablename__ = "endurance_runs"
    __table_args__ = (
        Index(
            "uq_endurance_runs_active",
            "project_id",
            unique=True,
            sqlite_where=text("status IN ('queued','running','paused','cancel_requested')"),
        ),
        Index(
            "uq_endurance_runs_idempotency",
            "project_id",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL AND idempotency_key != ''"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    suite_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    start_chapter: Mapped[int] = mapped_column(Integer)
    end_chapter: Mapped[int] = mapped_column(Integer)
    target_chapter_count: Mapped[int] = mapped_column(Integer, default=5)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    current_automation_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    current_automation_run_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    last_checkpoint_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    stop_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    diagnostic_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class EnduranceCheckpoint(ProjectBase):
    __tablename__ = "endurance_checkpoints"
    __table_args__ = (Index("uq_endurance_checkpoints_run_chapter", "run_id", "chapter_number", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    automation_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    automation_run_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    chapter_number: Mapped[int] = mapped_column(Integer, index=True)
    chapter_commit_id: Mapped[str] = mapped_column(String(36), index=True)
    source_version_id: Mapped[str] = mapped_column(String(36), index=True)
    state_snapshot_id: Mapped[str] = mapped_column(String(36), index=True)
    commit_revision: Mapped[int] = mapped_column(Integer)
    source_revision: Mapped[int] = mapped_column(Integer)
    snapshot_revision: Mapped[int] = mapped_column(Integer)
    commit_checksum: Mapped[str] = mapped_column(String(64), default="")
    source_checksum: Mapped[str] = mapped_column(String(64), default="")
    snapshot_checksum: Mapped[str] = mapped_column(String(64), default="")
    canon_revision: Mapped[int] = mapped_column(Integer, default=0)
    plan_revision: Mapped[int] = mapped_column(Integer, default=0)
    budget_summary_json: Mapped[str] = mapped_column(Text, default="{}")
    character_knowledge_json: Mapped[str] = mapped_column(Text, default="{}")
    ability_summary_json: Mapped[str] = mapped_column(Text, default="{}")
    item_summary_json: Mapped[str] = mapped_column(Text, default="{}")
    foreshadow_summary_json: Mapped[str] = mapped_column(Text, default="{}")
    cost_summary_json: Mapped[str] = mapped_column(Text, default="{}")
    checkpoint_checksum: Mapped[str] = mapped_column(String(64), default="")
    validation_status: Mapped[str] = mapped_column(String(20), default="validated", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class EnduranceFinding(ProjectBase):
    __tablename__ = "endurance_findings"
    __table_args__ = (Index("uq_endurance_findings_run_fingerprint", "run_id", "fingerprint", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    checkpoint_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    rule_code: Mapped[str] = mapped_column(String(120), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    chapter_number: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    suggestion: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class EnduranceReport(ProjectBase):
    __tablename__ = "endurance_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    run_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    isolated_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    average_revision_rounds: Mapped[float] = mapped_column(Float, default=0.0)
    quality_trend_json: Mapped[str] = mapped_column(Text, default="{}")
    drift_trend_json: Mapped[str] = mapped_column(Text, default="{}")
    stop_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AdaptationWorkspace(ProjectBase):
    __tablename__ = "adaptation_workspaces"
    __table_args__ = (
        Index(
            "uq_adaptation_workspaces_active_name",
            "project_id",
            "name",
            unique=True,
            sqlite_where=text("status != 'archived'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(30), index=True)
    source_type: Mapped[str] = mapped_column(String(40), default="canon", index=True)
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    source_manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    canon_revision: Mapped[int] = mapped_column(Integer, default=0)
    canon_checksum: Mapped[str] = mapped_column(String(64), default="")
    plan_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plan_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    commit_manifest_json: Mapped[str] = mapped_column(Text, default="[]")
    target_word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_chapter_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_episode_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audience: Mapped[str] = mapped_column(String(160), default="")
    platform_constraints_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    diagnostic_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ShortStoryStrategy(ProjectBase):
    __tablename__ = "short_story_strategies"
    __table_args__ = (
        Index(
            "uq_short_story_strategies_current",
            "workspace_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    core_hook: Mapped[str] = mapped_column(Text, default="")
    opening_hook: Mapped[str] = mapped_column(Text, default="")
    main_conflict: Mapped[str] = mapped_column(Text, default="")
    emotional_curve_json: Mapped[str] = mapped_column(Text, default="[]")
    ending: Mapped[str] = mapped_column(Text, default="")
    point_of_view: Mapped[str] = mapped_column(String(120), default="")
    target_word_count: Mapped[int] = mapped_column(Integer, default=10000)
    chapter_budget_json: Mapped[str] = mapped_column(Text, default="[]")
    character_merge_plan_json: Mapped[str] = mapped_column(Text, default="[]")
    foreshadow_plan_json: Mapped[str] = mapped_column(Text, default="{}")
    compression_rules_json: Mapped[str] = mapped_column(Text, default="{}")
    forbidden_reveals_json: Mapped[str] = mapped_column(Text, default="[]")
    checksum: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AdaptationProposal(ProjectBase):
    __tablename__ = "adaptation_proposals"
    __table_args__ = (
        Index(
            "uq_adaptation_proposals_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL AND idempotency_key != ''"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    proposal_kind: Mapped[str] = mapped_column(String(40), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    input_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    structured_output_json: Mapped[str] = mapped_column(Text, default="{}")
    diff_json: Mapped[str] = mapped_column(Text, default="{}")
    impact_scope_json: Mapped[str] = mapped_column(Text, default="[]")
    canon_deviations_json: Mapped[str] = mapped_column(Text, default="[]")
    model_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DramaEpisode(ProjectBase):
    __tablename__ = "drama_episodes"
    __table_args__ = (
        Index("uq_drama_episodes_workspace_number", "workspace_id", "episode_number", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    episode_number: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(240), default="")
    logline: Mapped[str] = mapped_column(Text, default="")
    target_duration_seconds: Mapped[int] = mapped_column(Integer, default=90)
    opening_hook: Mapped[str] = mapped_column(Text, default="")
    cliffhanger: Mapped[str] = mapped_column(Text, default="")
    source_refs_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DramaScene(ProjectBase):
    __tablename__ = "drama_scenes"
    __table_args__ = (
        Index("uq_drama_scenes_episode_number", "episode_id", "scene_number", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    episode_id: Mapped[str] = mapped_column(String(36), index=True)
    scene_number: Mapped[int] = mapped_column(Integer, index=True)
    setting_type: Mapped[str] = mapped_column(String(40), default="")
    location: Mapped[str] = mapped_column(String(240), default="")
    time_of_day: Mapped[str] = mapped_column(String(40), default="")
    characters_json: Mapped[str] = mapped_column(Text, default="[]")
    objective: Mapped[str] = mapped_column(Text, default="")
    conflict: Mapped[str] = mapped_column(Text, default="")
    turn: Mapped[str] = mapped_column(Text, default="")
    visual_action: Mapped[str] = mapped_column(Text, default="")
    estimated_duration_seconds: Mapped[int] = mapped_column(Integer, default=30)
    source_evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    canon_refs_json: Mapped[str] = mapped_column(Text, default="[]")
    checksum: Mapped[str] = mapped_column(String(64), default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DramaScriptVersion(ProjectBase):
    __tablename__ = "drama_script_versions"
    __table_args__ = (
        Index(
            "uq_drama_script_versions_current_approved",
            "episode_id",
            unique=True,
            sqlite_where=text("status = 'approved' AND is_current = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    episode_id: Mapped[str] = mapped_column(String(36), index=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    parent_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(40), default="candidate", index=True)
    fountain_text: Mapped[str] = mapped_column(Text, default="")
    markdown_text: Mapped[str] = mapped_column(Text, default="")
    structured_dialogue_json: Mapped[str] = mapped_column(Text, default="[]")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    estimated_duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    model_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(20), default="candidate", index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdaptationFinding(ProjectBase):
    __tablename__ = "adaptation_findings"
    __table_args__ = (
        Index("uq_adaptation_findings_workspace_fingerprint", "workspace_id", "fingerprint", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    proposal_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    episode_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    scene_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    rule_code: Mapped[str] = mapped_column(String(120), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    suggestion: Mapped[str] = mapped_column(Text, default="")
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ShortStoryOrigin(ProjectBase):
    __tablename__ = "short_story_origins"
    __table_args__ = (
        Index(
            "uq_short_story_origins_idempotency",
            "project_id",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL AND idempotency_key != ''"),
        ),
        Index("uq_short_story_origins_target", "target_project_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    source_project_id: Mapped[str] = mapped_column(String(36), index=True)
    source_workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    source_strategy_id: Mapped[str] = mapped_column(String(36), index=True)
    source_strategy_revision: Mapped[int] = mapped_column(Integer)
    source_strategy_checksum: Mapped[str] = mapped_column(String(64))
    source_manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    strategy_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    target_project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    target_title: Mapped[str] = mapped_column(String(200), default="")
    target_chapter_count: Mapped[int] = mapped_column(Integer, default=1)
    target_word_count: Mapped[int] = mapped_column(Integer, default=10000)
    status: Mapped[str] = mapped_column(String(30), default="creating", index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    diagnostic_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
