"""chapter pipeline foundation"""
from alembic import op
import sqlalchemy as sa

revision = "0006_chapter_pipeline"
down_revision = "0005_phase4_audit_fixes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chapter_contracts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("chapter_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("plan_node_id", sa.String(60), nullable=True),
        sa.Column("plan_node_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("canon_revision_digest", sa.String(64), nullable=False, server_default=""),
        sa.Column("state_snapshot_id", sa.String(36), nullable=True),
        sa.Column("objective_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("allowed_scope_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("forbidden_scope_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("required_characters_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("required_foreshadows_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("required_hooks_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("completion_conditions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("pov", sa.String(120), nullable=False, server_default=""),
        sa.Column("target_words_min", sa.Integer(), nullable=False, server_default="1500"),
        sa.Column("target_words_max", sa.Integer(), nullable=False, server_default="3000"),
        sa.Column("pace", sa.String(40), nullable=False, server_default="smooth"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_chapter_contracts_project_id", "chapter_contracts", ["project_id"])
    op.create_index("ix_chapter_contracts_chapter_number", "chapter_contracts", ["chapter_number"])
    op.create_index("ix_chapter_contracts_plan_node_id", "chapter_contracts", ["plan_node_id"])
    op.create_index("ix_chapter_contracts_state_snapshot_id", "chapter_contracts", ["state_snapshot_id"])
    op.create_index("ix_chapter_contracts_status", "chapter_contracts", ["status"])
    op.create_index(
        "uq_chapter_contracts_locked",
        "chapter_contracts",
        ["project_id", "chapter_number"],
        unique=True,
        sqlite_where=sa.text("status = 'locked'"),
    )

    op.create_table(
        "chapter_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("chapter_contract_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("current_revision_round", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("context_trace_id", sa.String(36), nullable=True),
        sa.Column("idempotency_key", sa.String(120), nullable=False, server_default=""),
        sa.Column("lease_owner", sa.String(120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("diagnostic_json", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chapter_jobs_project_id", "chapter_jobs", ["project_id"])
    op.create_index("ix_chapter_jobs_chapter_contract_id", "chapter_jobs", ["chapter_contract_id"])
    op.create_index("ix_chapter_jobs_status", "chapter_jobs", ["status"])
    op.create_index("ix_chapter_jobs_context_trace_id", "chapter_jobs", ["context_trace_id"])
    op.create_index("ix_chapter_jobs_error_code", "chapter_jobs", ["error_code"])
    op.create_index("uq_chapter_jobs_idempotency", "chapter_jobs", ["project_id", "chapter_contract_id", "idempotency_key"], unique=True)

    op.create_table(
        "chapter_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("chapter_job_id", sa.String(36), nullable=False),
        sa.Column("chapter_contract_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("parent_draft_id", sa.String(36), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False, server_default="generated"),
        sa.Column("content_markdown", sa.Text(), nullable=False, server_default=""),
        sa.Column("word_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("model_run_id", sa.String(36), nullable=True),
        sa.Column("context_trace_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="candidate"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chapter_drafts_project_id", "chapter_drafts", ["project_id"])
    op.create_index("ix_chapter_drafts_chapter_job_id", "chapter_drafts", ["chapter_job_id"])
    op.create_index("ix_chapter_drafts_chapter_contract_id", "chapter_drafts", ["chapter_contract_id"])
    op.create_index("ix_chapter_drafts_parent_draft_id", "chapter_drafts", ["parent_draft_id"])
    op.create_index("ix_chapter_drafts_kind", "chapter_drafts", ["kind"])
    op.create_index("ix_chapter_drafts_model_run_id", "chapter_drafts", ["model_run_id"])
    op.create_index("ix_chapter_drafts_context_trace_id", "chapter_drafts", ["context_trace_id"])
    op.create_index("ix_chapter_drafts_status", "chapter_drafts", ["status"])
    op.create_index("uq_chapter_drafts_job_version", "chapter_drafts", ["chapter_job_id", "version_number"], unique=True)

    op.create_table(
        "chapter_extractions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("chapter_draft_id", sa.String(36), nullable=False),
        sa.Column("model_run_id", sa.String(36), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="candidate"),
        sa.Column("validation_errors_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chapter_extractions_project_id", "chapter_extractions", ["project_id"])
    op.create_index("ix_chapter_extractions_chapter_draft_id", "chapter_extractions", ["chapter_draft_id"])
    op.create_index("ix_chapter_extractions_model_run_id", "chapter_extractions", ["model_run_id"])
    op.create_index("ix_chapter_extractions_status", "chapter_extractions", ["status"])

    op.create_table(
        "quality_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("chapter_job_id", sa.String(36), nullable=False),
        sa.Column("chapter_draft_id", sa.String(36), nullable=False),
        sa.Column("gate_type", sa.String(30), nullable=False),
        sa.Column("reviewer_role", sa.String(80), nullable=True),
        sa.Column("model_run_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_quality_runs_project_id", "quality_runs", ["project_id"])
    op.create_index("ix_quality_runs_chapter_job_id", "quality_runs", ["chapter_job_id"])
    op.create_index("ix_quality_runs_chapter_draft_id", "quality_runs", ["chapter_draft_id"])
    op.create_index("ix_quality_runs_gate_type", "quality_runs", ["gate_type"])
    op.create_index("ix_quality_runs_reviewer_role", "quality_runs", ["reviewer_role"])
    op.create_index("ix_quality_runs_model_run_id", "quality_runs", ["model_run_id"])
    op.create_index("ix_quality_runs_status", "quality_runs", ["status"])

    op.create_table(
        "quality_findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("quality_run_id", sa.String(36), nullable=False),
        sa.Column("chapter_draft_id", sa.String(36), nullable=False),
        sa.Column("rule_code", sa.String(120), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("location_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("suggested_fix", sa.Text(), nullable=False, server_default=""),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("accepted_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_quality_findings_project_id", "quality_findings", ["project_id"])
    op.create_index("ix_quality_findings_quality_run_id", "quality_findings", ["quality_run_id"])
    op.create_index("ix_quality_findings_chapter_draft_id", "quality_findings", ["chapter_draft_id"])
    op.create_index("ix_quality_findings_rule_code", "quality_findings", ["rule_code"])
    op.create_index("ix_quality_findings_severity", "quality_findings", ["severity"])
    op.create_index("ix_quality_findings_category", "quality_findings", ["category"])
    op.create_index("ix_quality_findings_fingerprint", "quality_findings", ["fingerprint"])
    op.create_index("ix_quality_findings_status", "quality_findings", ["status"])
    op.create_index("uq_quality_findings_draft_fingerprint", "quality_findings", ["chapter_draft_id", "fingerprint"], unique=True)

    op.create_table(
        "chapter_commits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("chapter_number", sa.Integer(), nullable=False),
        sa.Column("chapter_contract_id", sa.String(36), nullable=False),
        sa.Column("approved_draft_id", sa.String(36), nullable=False),
        sa.Column("source_version_id", sa.String(36), nullable=False),
        sa.Column("state_snapshot_id", sa.String(36), nullable=True),
        sa.Column("quality_summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="official"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chapter_commits_project_id", "chapter_commits", ["project_id"])
    op.create_index("ix_chapter_commits_chapter_number", "chapter_commits", ["chapter_number"])
    op.create_index("ix_chapter_commits_chapter_contract_id", "chapter_commits", ["chapter_contract_id"])
    op.create_index("ix_chapter_commits_approved_draft_id", "chapter_commits", ["approved_draft_id"])
    op.create_index("ix_chapter_commits_source_version_id", "chapter_commits", ["source_version_id"])
    op.create_index("ix_chapter_commits_state_snapshot_id", "chapter_commits", ["state_snapshot_id"])
    op.create_index("ix_chapter_commits_status", "chapter_commits", ["status"])
    op.create_index("ix_chapter_commits_is_current", "chapter_commits", ["is_current"])
    op.create_index(
        "uq_chapter_commits_current",
        "chapter_commits",
        ["project_id", "chapter_number"],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
    )


def downgrade() -> None:
    op.drop_table("chapter_commits")
    op.drop_table("quality_findings")
    op.drop_table("quality_runs")
    op.drop_table("chapter_extractions")
    op.drop_table("chapter_drafts")
    op.drop_table("chapter_jobs")
    op.drop_table("chapter_contracts")
