"""story architecture proposals and plot budgets"""

from alembic import op
import sqlalchemy as sa


revision = "0012_story_architecture"
down_revision = "0011_plan_node_chapter_beats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("project_meta", sa.Column("project_kind", sa.String(20), nullable=False, server_default="standard"))
    op.create_table(
        "canon_generation_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("base_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("brief_json", sa.Text(), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column("structured_json", sa.Text(), nullable=False),
        sa.Column("readiness_json", sa.Text(), nullable=False),
        sa.Column("model_run_id", sa.String(36), nullable=True, index=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "plan_generation_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("base_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("validation_json", sa.Text(), nullable=False),
        sa.Column("model_run_id", sa.String(36), nullable=True, index=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "story_budgets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("category", sa.String(40), nullable=False, index=True),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("earliest_chapter", sa.Integer(), nullable=False),
        sa.Column("target_min", sa.Integer(), nullable=False),
        sa.Column("target_max", sa.Integer(), nullable=False),
        sa.Column("latest_chapter", sa.Integer(), nullable=False),
        sa.Column("prerequisites_json", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("consumed_chapter", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "code", name="uq_story_budgets_project_code"),
    )


def downgrade() -> None:
    op.drop_table("story_budgets")
    op.drop_table("plan_generation_proposals")
    op.drop_table("canon_generation_proposals")
    op.drop_column("project_meta", "project_kind")
