"""automation foundation"""

from alembic import op
import sqlalchemy as sa


revision = "0008_automation_foundation"
down_revision = "0007_chapter_draft_current"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "automation_policies",
        sa.Column("project_id", sa.String(36), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("time_of_day", sa.String(5), nullable=False, server_default="03:00"),
        sa.Column("timezone", sa.String(80), nullable=False, server_default="UTC"),
        sa.Column("chapters_per_run", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("target_words_min", sa.Integer(), nullable=False, server_default="1500"),
        sa.Column("target_words_max", sa.Integer(), nullable=False, server_default="3000"),
        sa.Column("max_revision_rounds", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("daily_cost_limit", sa.Float(), nullable=True),
        sa.Column("stop_policy", sa.String(40), nullable=False, server_default="stop_on_blocking"),
        sa.Column("approval_mode", sa.String(40), nullable=False, server_default="guarded_auto"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_scheduled_local_date", sa.String(10), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("chapters_per_run >= 1 AND chapters_per_run <= 10", name="ck_automation_policies_chapters_per_run"),
        sa.CheckConstraint("target_words_min >= 1 AND target_words_max >= target_words_min", name="ck_automation_policies_word_target"),
        sa.CheckConstraint("max_revision_rounds >= 0 AND max_revision_rounds <= 2", name="ck_automation_policies_revision_rounds"),
        sa.CheckConstraint("daily_cost_limit IS NULL OR daily_cost_limit >= 0", name="ck_automation_policies_daily_cost"),
        sa.CheckConstraint("stop_policy IN ('stop_on_blocking', 'stop_on_any_failure')", name="ck_automation_policies_stop_policy"),
        sa.CheckConstraint("approval_mode IN ('guarded_auto')", name="ck_automation_policies_approval_mode"),
    )
    op.create_index("ix_automation_policies_enabled", "automation_policies", ["enabled"])
    op.create_index("ix_automation_policies_next_run_at", "automation_policies", ["next_run_at"])

    op.create_table(
        "automation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("policy_id", sa.String(36), nullable=False),
        sa.Column("scheduled_local_date", sa.String(10), nullable=False),
        sa.Column("trigger", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("idempotency_key", sa.String(120), nullable=True),
        sa.Column("start_chapter", sa.Integer(), nullable=True),
        sa.Column("end_chapter", sa.Integer(), nullable=True),
        sa.Column("planned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("isolated_count", sa.Integer(), nullable=False, server_default="0"),
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
        sa.CheckConstraint("trigger IN ('scheduled', 'manual', 'catch_up')", name="ck_automation_runs_trigger"),
    )
    op.create_index("ix_automation_runs_project_id", "automation_runs", ["project_id"])
    op.create_index("ix_automation_runs_policy_id", "automation_runs", ["policy_id"])
    op.create_index("ix_automation_runs_scheduled_local_date", "automation_runs", ["scheduled_local_date"])
    op.create_index("ix_automation_runs_trigger", "automation_runs", ["trigger"])
    op.create_index("ix_automation_runs_status", "automation_runs", ["status"])
    op.create_index(
        "uq_automation_runs_scheduled_date",
        "automation_runs",
        ["project_id", "scheduled_local_date"],
        unique=True,
        sqlite_where=sa.text("trigger = 'scheduled'"),
    )
    op.create_index(
        "uq_automation_runs_idempotency",
        "automation_runs",
        ["project_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL AND idempotency_key != ''"),
    )

    op.create_table(
        "automation_run_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("automation_run_id", sa.String(36), nullable=False),
        sa.Column("chapter_number", sa.Integer(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("chapter_contract_id", sa.String(36), nullable=True),
        sa.Column("chapter_job_id", sa.String(36), nullable=True),
        sa.Column("chapter_commit_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="waiting"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("diagnostic_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_automation_run_items_project_id", "automation_run_items", ["project_id"])
    op.create_index("ix_automation_run_items_automation_run_id", "automation_run_items", ["automation_run_id"])
    op.create_index("ix_automation_run_items_chapter_number", "automation_run_items", ["chapter_number"])
    op.create_index("ix_automation_run_items_chapter_contract_id", "automation_run_items", ["chapter_contract_id"])
    op.create_index("ix_automation_run_items_chapter_job_id", "automation_run_items", ["chapter_job_id"])
    op.create_index("ix_automation_run_items_chapter_commit_id", "automation_run_items", ["chapter_commit_id"])
    op.create_index("ix_automation_run_items_status", "automation_run_items", ["status"])
    op.create_index("ix_automation_run_items_error_code", "automation_run_items", ["error_code"])
    op.create_index("uq_automation_run_items_chapter", "automation_run_items", ["automation_run_id", "chapter_number"], unique=True)

    op.create_table(
        "automation_leases",
        sa.Column("project_id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(120), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_automation_leases_owner_id", "automation_leases", ["owner_id"])
    op.create_index("ix_automation_leases_lease_expires_at", "automation_leases", ["lease_expires_at"])


def downgrade() -> None:
    op.drop_table("automation_leases")
    op.drop_table("automation_run_items")
    op.drop_table("automation_runs")
    op.drop_table("automation_policies")
