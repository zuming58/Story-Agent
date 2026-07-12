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
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
