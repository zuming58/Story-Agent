"""canon memory foundation"""
from alembic import op
import sqlalchemy as sa

revision = "0004_canon_memory"
down_revision = "0003_structured_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canon_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_canon_documents_kind", "canon_documents", ["kind"])
    op.create_index("ix_canon_documents_status", "canon_documents", ["status"])

    op.create_table(
        "canon_entity_types",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("schema_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_document_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_canon_entity_types_name", "canon_entity_types", ["name"], unique=True)
    op.create_index("ix_canon_entity_types_status", "canon_entity_types", ["status"])

    op.create_table(
        "canon_entities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_type_id", sa.String(36), nullable=False),
        sa.Column("canonical_name", sa.String(240), nullable=False),
        sa.Column("aliases_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("attributes_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_document_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_canon_entities_entity_type_id", "canon_entities", ["entity_type_id"])
    op.create_index("ix_canon_entities_canonical_name", "canon_entities", ["canonical_name"], unique=True)
    op.create_index("ix_canon_entities_status", "canon_entities", ["status"])

    op.create_table(
        "canon_relations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("subject_entity_id", sa.String(36), nullable=False),
        sa.Column("predicate", sa.String(120), nullable=False),
        sa.Column("object_entity_id", sa.String(36), nullable=True),
        sa.Column("object_value_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_document_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_canon_relations_subject_entity_id", "canon_relations", ["subject_entity_id"])
    op.create_index("ix_canon_relations_predicate", "canon_relations", ["predicate"])
    op.create_index("ix_canon_relations_object_entity_id", "canon_relations", ["object_entity_id"])

    op.create_table(
        "canon_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("rule_code", sa.String(120), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("constraint_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_document_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_canon_rules_rule_code", "canon_rules", ["rule_code"], unique=True)
    op.create_index("ix_canon_rules_category", "canon_rules", ["category"])
    op.create_index("ix_canon_rules_status", "canon_rules", ["status"])

    op.create_table(
        "canon_change_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("target_kind", sa.String(40), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("impact_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("before_json", sa.Text(), nullable=True),
        sa.Column("after_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_canon_change_requests_project_id", "canon_change_requests", ["project_id"])
    op.create_index("ix_canon_change_requests_target_kind", "canon_change_requests", ["target_kind"])
    op.create_index("ix_canon_change_requests_target_id", "canon_change_requests", ["target_id"])
    op.create_index("ix_canon_change_requests_status", "canon_change_requests", ["status"])

    op.create_table(
        "source_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("source_id", sa.String(120), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_kind", sa.String(40), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(20), nullable=False, server_default="candidate"),
        sa.Column("checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_source_versions_project_id", "source_versions", ["project_id"])
    op.create_index("ix_source_versions_source_id", "source_versions", ["source_id"])
    op.create_index("ix_source_versions_status", "source_versions", ["status"])

    op.create_table(
        "story_entities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("entity_type_id", sa.String(36), nullable=False),
        sa.Column("canonical_name", sa.String(240), nullable=False),
        sa.Column("aliases_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("attributes_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_document_id", sa.String(36), nullable=True),
        sa.Column("source_version_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_story_entities_project_id", "story_entities", ["project_id"])
    op.create_index("ix_story_entities_entity_type_id", "story_entities", ["entity_type_id"])
    op.create_index("ix_story_entities_canonical_name", "story_entities", ["canonical_name"], unique=True)
    op.create_index("ix_story_entities_source_version_id", "story_entities", ["source_version_id"])

    op.create_table(
        "state_facts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("field_path", sa.String(240), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False, server_default="null"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_version_id", sa.String(36), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_state_facts_project_id", "state_facts", ["project_id"])
    op.create_index("ix_state_facts_entity_id", "state_facts", ["entity_id"])
    op.create_index("ix_state_facts_field_path", "state_facts", ["field_path"])
    op.create_index("ix_state_facts_source_version_id", "state_facts", ["source_version_id"])
    op.create_index("ix_state_facts_is_current", "state_facts", ["is_current"])

    op.create_table(
        "story_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("event_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("location", sa.String(200), nullable=False, server_default=""),
        sa.Column("participants_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_version_id", sa.String(36), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_story_events_project_id", "story_events", ["project_id"])
    op.create_index("ix_story_events_event_order", "story_events", ["event_order"])
    op.create_index("ix_story_events_source_version_id", "story_events", ["source_version_id"])

    op.create_table(
        "state_deltas",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("event_id", sa.String(36), nullable=True),
        sa.Column("field_path", sa.String(240), nullable=False),
        sa.Column("before_json", sa.Text(), nullable=True),
        sa.Column("after_json", sa.Text(), nullable=True),
        sa.Column("source_version_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="official"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_state_deltas_project_id", "state_deltas", ["project_id"])
    op.create_index("ix_state_deltas_event_id", "state_deltas", ["event_id"])
    op.create_index("ix_state_deltas_field_path", "state_deltas", ["field_path"])
    op.create_index("ix_state_deltas_source_version_id", "state_deltas", ["source_version_id"])
    op.create_index("ix_state_deltas_status", "state_deltas", ["status"])

    op.create_table(
        "foreshadows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("label", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("earliest_chapter", sa.Integer(), nullable=True),
        sa.Column("target_chapter", sa.Integer(), nullable=True),
        sa.Column("latest_chapter", sa.Integer(), nullable=True),
        sa.Column("source_version_id", sa.String(36), nullable=True),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_foreshadows_project_id", "foreshadows", ["project_id"])
    op.create_index("ix_foreshadows_code", "foreshadows", ["code"])
    op.create_index("ix_foreshadows_status", "foreshadows", ["status"])
    op.create_index("ix_foreshadows_source_version_id", "foreshadows", ["source_version_id"])

    op.create_table(
        "knowledge_boundaries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("source_version_id", sa.String(36), nullable=True),
        sa.Column("knowledge_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_knowledge_boundaries_project_id", "knowledge_boundaries", ["project_id"])
    op.create_index("ix_knowledge_boundaries_entity_id", "knowledge_boundaries", ["entity_id"])
    op.create_index("ix_knowledge_boundaries_source_version_id", "knowledge_boundaries", ["source_version_id"])

    op.create_table(
        "state_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("snapshot_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_version_id", sa.String(36), nullable=True),
        sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_state_snapshots_project_id", "state_snapshots", ["project_id"])
    op.create_index("ix_state_snapshots_snapshot_number", "state_snapshots", ["snapshot_number"])
    op.create_index("ix_state_snapshots_source_version_id", "state_snapshots", ["source_version_id"])

    op.create_table(
        "retrieval_index_entries",
        sa.Column("rowid", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entry_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_version_id", sa.String(36), nullable=True),
        sa.Column("entity_id", sa.String(36), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("source_status", sa.String(20), nullable=False, server_default="official"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_retrieval_index_entries_entry_id", "retrieval_index_entries", ["entry_id"], unique=True)
    op.create_index("ix_retrieval_index_entries_project_id", "retrieval_index_entries", ["project_id"])
    op.create_index("ix_retrieval_index_entries_source_version_id", "retrieval_index_entries", ["source_version_id"])
    op.create_index("ix_retrieval_index_entries_entity_id", "retrieval_index_entries", ["entity_id"])
    op.create_index("ix_retrieval_index_entries_kind", "retrieval_index_entries", ["kind"])

    op.execute(
        """
        CREATE VIRTUAL TABLE retrieval_fts USING fts5(
            project_id UNINDEXED,
            kind,
            title,
            content,
            source_version_id UNINDEXED,
            entity_id UNINDEXED,
            checksum UNINDEXED,
            source_status UNINDEXED,
            content='retrieval_index_entries',
            content_rowid='rowid'
        )
        """
    )

    op.create_table(
        "retrieval_index_state",
        sa.Column("project_id", sa.String(36), primary_key=True),
        sa.Column("last_rebuilt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("indexed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("vector_backend", sa.String(60), nullable=False, server_default="sqlite-local"),
        sa.Column("vector_available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "context_traces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(80), nullable=False),
        sa.Column("query", sa.Text(), nullable=False, server_default=""),
        sa.Column("selected_node_id", sa.String(60), nullable=True),
        sa.Column("token_budget", sa.Integer(), nullable=False, server_default="4000"),
        sa.Column("package_json", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_context_traces_project_id", "context_traces", ["project_id"])
    op.create_index("ix_context_traces_role", "context_traces", ["role"])
    op.create_index("ix_context_traces_selected_node_id", "context_traces", ["selected_node_id"])


def downgrade() -> None:
    op.drop_table("context_traces")
    op.drop_table("retrieval_index_state")
    op.execute("DROP TABLE IF EXISTS retrieval_fts")
    op.drop_table("retrieval_index_entries")
    op.drop_table("state_snapshots")
    op.drop_table("knowledge_boundaries")
    op.drop_table("foreshadows")
    op.drop_table("state_deltas")
    op.drop_table("story_events")
    op.drop_table("state_facts")
    op.drop_table("story_entities")
    op.drop_table("source_versions")
    op.drop_table("canon_change_requests")
    op.drop_table("canon_rules")
    op.drop_table("canon_relations")
    op.drop_table("canon_entities")
    op.drop_table("canon_entity_types")
    op.drop_table("canon_documents")
