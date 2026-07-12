"""model provider configuration"""
from alembic import op
import sqlalchemy as sa

revision = "0002_model_provider"
down_revision = "0001_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_providers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("provider_type", sa.String(60), nullable=False, server_default="openai-compatible"),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("api_key_ref", sa.String(240), nullable=True),
        sa.Column("api_key_preview", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "model_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider_id", sa.String(36), sa.ForeignKey("model_providers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False, server_default="2048"),
        sa.Column("supports_reasoning", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_model_configs_provider_id", "model_configs", ["provider_id"])
    op.create_table(
        "model_role_bindings",
        sa.Column("role", sa.String(80), primary_key=True),
        sa.Column("model_id", sa.String(36), sa.ForeignKey("model_configs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("daily_cost_limit", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_model_role_bindings_model_id", "model_role_bindings", ["model_id"])


def downgrade() -> None:
    op.drop_table("model_role_bindings")
    op.drop_table("model_configs")
    op.drop_table("model_providers")
