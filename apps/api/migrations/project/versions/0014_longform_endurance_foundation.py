"""longform endurance foundation"""

from alembic import op
import sqlalchemy as sa


revision = "0014_longform_endurance_foundation"
down_revision = "0013_export_publishing_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "endurance_suites",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("start_chapter", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("target_chapter_count", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("daily_cost_limit", sa.Float(), nullable=True),
        sa.Column("total_cost_limit", sa.Float(), nullable=True),
        sa.Column("consecutive_failure_limit", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("stop_severity", sa.String(20), nullable=False, server_default="blocker"),
        sa.Column("enabled_rules_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "endurance_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("suite_id", sa.String(36), nullable=False, index=True),
        sa.Column("status", sa.String(30), nullable=False, index=True),
        sa.Column("idempotency_key", sa.String(120), nullable=True),
        sa.Column("start_chapter", sa.Integer(), nullable=False),
        sa.Column("end_chapter", sa.Integer(), nullable=False),
        sa.Column("target_chapter_count", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_automation_run_id", sa.String(36), nullable=True, index=True),
        sa.Column("current_automation_run_item_id", sa.String(36), nullable=True, index=True),
        sa.Column("last_checkpoint_id", sa.String(36), nullable=True, index=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("stop_reason", sa.String(120), nullable=True),
        sa.Column("diagnostic_json", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_endurance_runs_active",
        "endurance_runs",
        ["project_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued','running','paused','cancel_requested')"),
    )
    op.create_index(
        "uq_endurance_runs_idempotency",
        "endurance_runs",
        ["project_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL AND idempotency_key != ''"),
    )
    op.create_table(
        "endurance_checkpoints",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("run_id", sa.String(36), nullable=False, index=True),
        sa.Column("automation_run_id", sa.String(36), nullable=True, index=True),
        sa.Column("automation_run_item_id", sa.String(36), nullable=True, index=True),
        sa.Column("chapter_number", sa.Integer(), nullable=False, index=True),
        sa.Column("chapter_commit_id", sa.String(36), nullable=False, index=True),
        sa.Column("source_version_id", sa.String(36), nullable=False, index=True),
        sa.Column("state_snapshot_id", sa.String(36), nullable=False, index=True),
        sa.Column("commit_revision", sa.Integer(), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("snapshot_revision", sa.Integer(), nullable=False),
        sa.Column("commit_checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("source_checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("snapshot_checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("canon_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("plan_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("budget_summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("character_knowledge_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("ability_summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("item_summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("foreshadow_summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("cost_summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("checkpoint_checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("validation_status", sa.String(20), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "chapter_number", name="uq_endurance_checkpoints_run_chapter"),
    )
    op.create_table(
        "endurance_findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("run_id", sa.String(36), nullable=False, index=True),
        sa.Column("checkpoint_id", sa.String(36), nullable=True, index=True),
        sa.Column("rule_code", sa.String(120), nullable=False, index=True),
        sa.Column("severity", sa.String(20), nullable=False, index=True),
        sa.Column("chapter_number", sa.Integer(), nullable=True, index=True),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("suggestion", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("fingerprint", sa.String(64), nullable=False, index=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "fingerprint", name="uq_endurance_findings_run_fingerprint"),
    )
    op.create_table(
        "endurance_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("run_id", sa.String(36), nullable=False, unique=True, index=True),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("isolated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("average_revision_rounds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("quality_trend_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("drift_trend_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("stop_reason", sa.String(120), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("endurance_reports")
    op.drop_table("endurance_findings")
    op.drop_table("endurance_checkpoints")
    op.drop_index("uq_endurance_runs_idempotency", table_name="endurance_runs")
    op.drop_index("uq_endurance_runs_active", table_name="endurance_runs")
    op.drop_table("endurance_runs")
    op.drop_table("endurance_suites")
