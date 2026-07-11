"""initial project schema"""
from alembic import op
import sqlalchemy as sa

revision = "0001_project"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_meta",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("mode", sa.String(40), nullable=False),
        sa.Column("current_chapter", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_chapters", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("book_title", sa.String(200), nullable=False),
        sa.Column("volume_title", sa.String(200), nullable=False),
        sa.Column("arc_title", sa.String(200), nullable=False),
        sa.Column("chapter_start", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("chapter_end", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "plan_nodes",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("target_chapter", sa.Integer(), nullable=False),
        sa.Column("range_min", sa.Integer(), nullable=False),
        sa.Column("range_max", sa.Integer(), nullable=False),
        sa.Column("importance", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("prerequisites_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("completion_conditions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("foreshadows_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("contracts_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("pace", sa.String(20), nullable=False, server_default="smooth"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_plan_nodes_plan_id", "plan_nodes", ["plan_id"])
    op.create_table(
        "story_markers",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("chapter", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
    )
    op.create_index("ix_story_markers_plan_id", "story_markers", ["plan_id"])
    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("scope_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False, server_default="idle"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_sessions_project_id", "agent_sessions", ["project_id"])
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_messages_session_id", "agent_messages", ["session_id"])
    op.create_table(
        "change_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("target_id", sa.String(60), nullable=False),
        sa.Column("target_title", sa.String(240), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_change_proposals_target_id", "change_proposals", ["target_id"])
    op.create_table(
        "change_operations",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("proposal_id", sa.String(36), sa.ForeignKey("change_proposals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field", sa.String(80), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("before_value", sa.Integer(), nullable=False),
        sa.Column("after_value", sa.Integer(), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_change_operations_proposal_id", "change_operations", ["proposal_id"])
    op.create_table(
        "proposal_impacts",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("proposal_id", sa.String(36), sa.ForeignKey("change_proposals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
    )
    op.create_index("ix_proposal_impacts_proposal_id", "proposal_impacts", ["proposal_id"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.String(80), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    op.create_index("ix_audit_events_entity_id", "audit_events", ["entity_id"])
    op.create_index("ix_audit_events_request_id", "audit_events", ["request_id"])


def downgrade() -> None:
    for table in ["audit_events", "proposal_impacts", "change_operations", "change_proposals", "agent_messages", "agent_sessions", "story_markers", "plan_nodes", "plans", "project_meta"]:
        op.drop_table(table)
