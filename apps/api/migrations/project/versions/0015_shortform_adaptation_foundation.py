"""shortform adaptation foundation"""

from alembic import op
import sqlalchemy as sa


revision = "0015_shortform_adaptation_foundation"
down_revision = "0014_longform_endurance_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "adaptation_workspaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False, index=True),
        sa.Column("source_type", sa.String(40), nullable=False, server_default="canon", index=True),
        sa.Column("source_id", sa.String(36), nullable=True, index=True),
        sa.Column("source_manifest_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("canon_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("canon_checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("plan_revision", sa.Integer(), nullable=True),
        sa.Column("plan_checksum", sa.String(64), nullable=True),
        sa.Column("commit_manifest_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("target_word_count", sa.Integer(), nullable=True),
        sa.Column("target_chapter_count", sa.Integer(), nullable=True),
        sa.Column("target_episode_count", sa.Integer(), nullable=True),
        sa.Column("unit_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("audience", sa.String(160), nullable=False, server_default=""),
        sa.Column("platform_constraints_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft", index=True),
        sa.Column("diagnostic_json", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_adaptation_workspaces_active_name",
        "adaptation_workspaces",
        ["project_id", "name"],
        unique=True,
        sqlite_where=sa.text("status != 'archived'"),
    )
    op.create_table(
        "short_story_strategies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("workspace_id", sa.String(36), nullable=False, index=True),
        sa.Column("core_hook", sa.Text(), nullable=False, server_default=""),
        sa.Column("opening_hook", sa.Text(), nullable=False, server_default=""),
        sa.Column("main_conflict", sa.Text(), nullable=False, server_default=""),
        sa.Column("emotional_curve_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("ending", sa.Text(), nullable=False, server_default=""),
        sa.Column("point_of_view", sa.String(120), nullable=False, server_default=""),
        sa.Column("target_word_count", sa.Integer(), nullable=False, server_default="10000"),
        sa.Column("chapter_budget_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("character_merge_plan_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("foreshadow_plan_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("compression_rules_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("forbidden_reveals_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="active", index=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_short_story_strategies_current",
        "short_story_strategies",
        ["workspace_id"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "adaptation_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("workspace_id", sa.String(36), nullable=False, index=True),
        sa.Column("proposal_kind", sa.String(40), nullable=False, index=True),
        sa.Column("idempotency_key", sa.String(120), nullable=True),
        sa.Column("input_snapshot_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("structured_output_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("diff_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("impact_scope_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("canon_deviations_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("model_run_id", sa.String(36), nullable=True, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column("error_code", sa.String(120), nullable=True, index=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_adaptation_proposals_idempotency",
        "adaptation_proposals",
        ["workspace_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL AND idempotency_key != ''"),
    )
    op.create_table(
        "drama_episodes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("workspace_id", sa.String(36), nullable=False, index=True),
        sa.Column("episode_number", sa.Integer(), nullable=False, index=True),
        sa.Column("title", sa.String(240), nullable=False, server_default=""),
        sa.Column("logline", sa.Text(), nullable=False, server_default=""),
        sa.Column("target_duration_seconds", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("opening_hook", sa.Text(), nullable=False, server_default=""),
        sa.Column("cliffhanger", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_refs_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft", index=True),
        sa.Column("checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "episode_number", name="uq_drama_episodes_workspace_number"),
    )
    op.create_table(
        "drama_scenes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("workspace_id", sa.String(36), nullable=False, index=True),
        sa.Column("episode_id", sa.String(36), nullable=False, index=True),
        sa.Column("scene_number", sa.Integer(), nullable=False, index=True),
        sa.Column("setting_type", sa.String(40), nullable=False, server_default=""),
        sa.Column("location", sa.String(240), nullable=False, server_default=""),
        sa.Column("time_of_day", sa.String(40), nullable=False, server_default=""),
        sa.Column("characters_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("objective", sa.Text(), nullable=False, server_default=""),
        sa.Column("conflict", sa.Text(), nullable=False, server_default=""),
        sa.Column("turn", sa.Text(), nullable=False, server_default=""),
        sa.Column("visual_action", sa.Text(), nullable=False, server_default=""),
        sa.Column("estimated_duration_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("source_evidence_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("canon_refs_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("episode_id", "scene_number", name="uq_drama_scenes_episode_number"),
    )
    op.create_table(
        "drama_script_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("workspace_id", sa.String(36), nullable=False, index=True),
        sa.Column("episode_id", sa.String(36), nullable=False, index=True),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("parent_version_id", sa.String(36), nullable=True, index=True),
        sa.Column("kind", sa.String(40), nullable=False, server_default="candidate", index=True),
        sa.Column("fountain_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("markdown_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("structured_dialogue_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("word_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_run_id", sa.String(36), nullable=True, index=True),
        sa.Column("checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="candidate", index=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="0", index=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_drama_script_versions_current_approved",
        "drama_script_versions",
        ["episode_id"],
        unique=True,
        sqlite_where=sa.text("status = 'approved' AND is_current = 1"),
    )
    op.create_table(
        "adaptation_findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("workspace_id", sa.String(36), nullable=False, index=True),
        sa.Column("proposal_id", sa.String(36), nullable=True, index=True),
        sa.Column("episode_id", sa.String(36), nullable=True, index=True),
        sa.Column("scene_id", sa.String(36), nullable=True, index=True),
        sa.Column("rule_code", sa.String(120), nullable=False, index=True),
        sa.Column("severity", sa.String(20), nullable=False, index=True),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("suggestion", sa.Text(), nullable=False, server_default=""),
        sa.Column("fingerprint", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open", index=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_adaptation_findings_workspace_fingerprint",
        "adaptation_findings",
        ["workspace_id", "fingerprint"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_adaptation_findings_workspace_fingerprint", table_name="adaptation_findings")
    op.drop_table("adaptation_findings")
    op.drop_index("uq_drama_script_versions_current_approved", table_name="drama_script_versions")
    op.drop_table("drama_script_versions")
    op.drop_table("drama_scenes")
    op.drop_table("drama_episodes")
    op.drop_index("uq_adaptation_proposals_idempotency", table_name="adaptation_proposals")
    op.drop_table("adaptation_proposals")
    op.drop_index("uq_short_story_strategies_current", table_name="short_story_strategies")
    op.drop_table("short_story_strategies")
    op.drop_index("uq_adaptation_workspaces_active_name", table_name="adaptation_workspaces")
    op.drop_table("adaptation_workspaces")
