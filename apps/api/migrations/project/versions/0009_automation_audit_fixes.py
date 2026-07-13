"""automation audit fixes and daily reports"""

from alembic import op
import sqlalchemy as sa


revision = "0009_automation_audit_fixes"
down_revision = "0008_automation_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_runs", sa.Column("automation_run_id", sa.String(36), nullable=True))
    op.add_column("model_runs", sa.Column("automation_run_item_id", sa.String(36), nullable=True))
    op.add_column("model_runs", sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"))
    op.create_index("ix_model_runs_automation_run_id", "model_runs", ["automation_run_id"])
    op.create_index("ix_model_runs_automation_run_item_id", "model_runs", ["automation_run_item_id"])

    op.create_table(
        "automation_daily_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("local_date", sa.String(10), nullable=False),
        sa.Column("timezone", sa.String(80), nullable=False, server_default="UTC"),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("planned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("isolated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status_summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_automation_daily_reports_project_id", "automation_daily_reports", ["project_id"])
    op.create_index("ix_automation_daily_reports_local_date", "automation_daily_reports", ["local_date"])
    op.create_index("uq_automation_daily_reports_date", "automation_daily_reports", ["project_id", "local_date"], unique=True)


def downgrade() -> None:
    op.drop_table("automation_daily_reports")
    op.drop_index("ix_model_runs_automation_run_item_id", table_name="model_runs")
    op.drop_index("ix_model_runs_automation_run_id", table_name="model_runs")
    op.drop_column("model_runs", "estimated_cost")
    op.drop_column("model_runs", "automation_run_item_id")
    op.drop_column("model_runs", "automation_run_id")
