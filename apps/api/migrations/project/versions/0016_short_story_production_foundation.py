"""short story production foundation"""

from alembic import op
import sqlalchemy as sa


revision = "0016_short_story_production_foundation"
down_revision = "0015_shortform_adaptation_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "short_story_origins",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("source_project_id", sa.String(36), nullable=False, index=True),
        sa.Column("source_workspace_id", sa.String(36), nullable=False, index=True),
        sa.Column("source_strategy_id", sa.String(36), nullable=False, index=True),
        sa.Column("source_strategy_revision", sa.Integer(), nullable=False),
        sa.Column("source_strategy_checksum", sa.String(64), nullable=False),
        sa.Column("source_manifest_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("strategy_snapshot_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("target_project_id", sa.String(36), nullable=True, index=True),
        sa.Column("target_title", sa.String(200), nullable=False, server_default=""),
        sa.Column("target_chapter_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("target_word_count", sa.Integer(), nullable=False, server_default="10000"),
        sa.Column("status", sa.String(30), nullable=False, server_default="creating", index=True),
        sa.Column("idempotency_key", sa.String(120), nullable=True),
        sa.Column("request_fingerprint", sa.String(64), nullable=False, server_default=""),
        sa.Column("diagnostic_json", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_short_story_origins_idempotency",
        "short_story_origins",
        ["project_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL AND idempotency_key != ''"),
    )
    op.create_index("uq_short_story_origins_target", "short_story_origins", ["target_project_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_short_story_origins_target", table_name="short_story_origins")
    op.drop_index("uq_short_story_origins_idempotency", table_name="short_story_origins")
    op.drop_table("short_story_origins")
