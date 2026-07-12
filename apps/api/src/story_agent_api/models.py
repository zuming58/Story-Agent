from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
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


class AgentMessage(ProjectBase):
    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    session: Mapped[AgentSession] = relationship(back_populates="messages")


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
