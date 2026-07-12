"""model run audit records"""
from alembic import op
import sqlalchemy as sa

revision = "0002_model_runs"
down_revision = "0001_project"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("agent_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("role", sa.String(80), nullable=False),
        sa.Column("provider_id", sa.String(36), nullable=True),
        sa.Column("provider_name", sa.String(160), nullable=False, server_default=""),
        sa.Column("model_config_id", sa.String(36), nullable=True),
        sa.Column("model_id", sa.String(200), nullable=False, server_default=""),
        sa.Column("status", sa.String(30), nullable=False, server_default="running"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_model_runs_session_id", "model_runs", ["session_id"])
    op.create_index("ix_model_runs_role", "model_runs", ["role"])
    op.create_index("ix_model_runs_status", "model_runs", ["status"])
    op.create_index("ix_model_runs_request_id", "model_runs", ["request_id"])


def downgrade() -> None:
    op.drop_table("model_runs")
