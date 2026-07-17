"""general story incubator foundation"""

from alembic import op
import sqlalchemy as sa


revision = "0017_general_story_incubator_foundation"
down_revision = "0016_short_story_production_foundation"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "market_research_briefs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("format", sa.String(40), nullable=False, index=True),
        sa.Column("platform", sa.String(160), nullable=False, server_default="undecided"),
        sa.Column("genre", sa.String(240), nullable=False),
        sa.Column("audience", sa.Text(), nullable=False),
        sa.Column("target_chapters", sa.Integer(), nullable=True),
        sa.Column("target_words", sa.Integer(), nullable=True),
        sa.Column("emotional_value_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("research_date_range_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("included_domains_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("excluded_domains_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("reference_works_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("forbidden_content_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("commercial_goals_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("checksum", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="current", index=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
    )
    op.create_index(
        "uq_market_research_briefs_current",
        "market_research_briefs",
        ["project_id"],
        unique=True,
        sqlite_where=sa.text("status = 'current'"),
    )
    op.create_table(
        "research_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("brief_id", sa.String(36), nullable=False, index=True),
        sa.Column("brief_revision", sa.Integer(), nullable=False),
        sa.Column("brief_checksum", sa.String(64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft", index=True),
        sa.Column("idempotency_key", sa.String(120), nullable=True),
        sa.Column("provider_config_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("limits_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("coverage_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("report_checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("report_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("query_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetched_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("request_units", sa.Float(), nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(120), nullable=True, index=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("diagnostic_json", sa.Text(), nullable=True),
        sa.Column("lease_owner", sa.String(160), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_research_jobs_idempotency",
        "research_jobs",
        ["project_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL AND idempotency_key != ''"),
    )
    op.create_table(
        "research_queries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("job_id", sa.String(36), nullable=False, index=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("perspective", sa.String(80), nullable=False, index=True),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued", index=True),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("request_units", sa.Float(), nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("provider_metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("uq_research_queries_job_fingerprint", "research_queries", ["job_id", "fingerprint"], unique=True)
    op.create_table(
        "research_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("job_id", sa.String(36), nullable=False, index=True),
        sa.Column("query_id", sa.String(36), nullable=True, index=True),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("domain", sa.String(240), nullable=False, index=True),
        sa.Column("source_type", sa.String(60), nullable=False, server_default="other", index=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(30), nullable=False, server_default="discovered", index=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("excluded", sa.Boolean(), nullable=False, server_default="0", index=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
    )
    op.create_index("uq_research_sources_job_url", "research_sources", ["job_id", "canonical_url"], unique=True)
    op.create_table(
        "research_source_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("job_id", sa.String(36), nullable=False, index=True),
        sa.Column("source_id", sa.String(36), nullable=False, index=True),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("final_url", sa.Text(), nullable=False),
        sa.Column("content_checksum", sa.String(64), nullable=False, index=True),
        sa.Column("bounded_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("char_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("fetch_metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_research_source_versions_checksum", "research_source_versions", ["source_id", "content_checksum"], unique=True)
    op.create_table(
        "research_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("job_id", sa.String(36), nullable=False, index=True),
        sa.Column("source_id", sa.String(36), nullable=False, index=True),
        sa.Column("source_version_id", sa.String(36), nullable=False, index=True),
        sa.Column("claim_type", sa.String(40), nullable=False, server_default="fact", index=True),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("locator_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("finding_refs_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("checksum", sa.String(64), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "competitor_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("job_id", sa.String(36), nullable=False, index=True),
        sa.Column("report_revision", sa.Integer(), nullable=False, server_default="1", index=True),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("profile_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("evidence_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("excluded", sa.Boolean(), nullable=False, server_default="0", index=True),
        sa.Column("exclusion_reason", sa.Text(), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active", index=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
    )
    op.create_table(
        "research_findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("job_id", sa.String(36), nullable=False, index=True),
        sa.Column("report_revision", sa.Integer(), nullable=False, server_default="1", index=True),
        sa.Column("category", sa.String(80), nullable=False, index=True),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.String(40), nullable=False, server_default="inference", index=True),
        sa.Column("evidence_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("uncertainties_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("checksum", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active", index=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "story_opportunities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("job_id", sa.String(36), nullable=False, index=True),
        sa.Column("report_revision", sa.Integer(), nullable=False),
        sa.Column("report_checksum", sa.String(64), nullable=False),
        sa.Column("high_concept", sa.Text(), nullable=False),
        sa.Column("story_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("score_components_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("total_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence_coverage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("uncertainties_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("evidence_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("checksum", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="0", index=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_story_opportunities_current",
        "story_opportunities",
        ["project_id"],
        unique=True,
        sqlite_where=sa.text("status = 'accepted' AND is_current = 1"),
    )
    op.create_table(
        "ideation_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("opportunity_id", sa.String(36), nullable=False, index=True),
        sa.Column("opportunity_revision", sa.Integer(), nullable=False),
        sa.Column("opportunity_checksum", sa.String(64), nullable=False),
        sa.Column("research_job_id", sa.String(36), nullable=False, index=True),
        sa.Column("research_report_checksum", sa.String(64), nullable=False),
        sa.Column("state_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active", index=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
    )
    op.create_table(
        "ideation_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("session_id", sa.String(36), nullable=False, index=True),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(30), nullable=False, index=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("structured_state_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("evidence_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("model_run_id", sa.String(36), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "story_brief_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("session_id", sa.String(36), nullable=False, index=True),
        sa.Column("proposal_id", sa.String(36), nullable=False, index=True),
        sa.Column("opportunity_id", sa.String(36), nullable=False, index=True),
        sa.Column("opportunity_checksum", sa.String(64), nullable=False),
        sa.Column("research_job_id", sa.String(36), nullable=False, index=True),
        sa.Column("research_report_checksum", sa.String(64), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("brief_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("checksum", sa.String(64), nullable=False, index=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="1", index=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_story_brief_versions_current", "story_brief_versions", ["project_id"], unique=True, sqlite_where=sa.text("is_current = 1"))
    op.create_table(
        "story_brief_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("session_id", sa.String(36), nullable=False, index=True),
        sa.Column("base_brief_version_id", sa.String(36), nullable=True, index=True),
        sa.Column("opportunity_id", sa.String(36), nullable=False, index=True),
        sa.Column("opportunity_revision", sa.Integer(), nullable=False),
        sa.Column("opportunity_checksum", sa.String(64), nullable=False),
        sa.Column("research_job_id", sa.String(36), nullable=False, index=True),
        sa.Column("research_report_checksum", sa.String(64), nullable=False),
        sa.Column("proposed_brief_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("diff_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("checksum", sa.String(64), nullable=False, index=True),
        sa.Column("model_run_id", sa.String(36), nullable=True, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "opening_experiments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("story_brief_version_id", sa.String(36), nullable=False, index=True),
        sa.Column("story_brief_revision", sa.Integer(), nullable=False),
        sa.Column("story_brief_checksum", sa.String(64), nullable=False),
        sa.Column("canon_document_id", sa.String(36), nullable=False, index=True),
        sa.Column("canon_revision", sa.Integer(), nullable=False),
        sa.Column("canon_checksum", sa.String(64), nullable=False),
        sa.Column("strategies_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(30), nullable=False, server_default="generating", index=True),
        sa.Column("selected_candidate_id", sa.String(36), nullable=True, index=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
    )
    op.create_table(
        "opening_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("experiment_id", sa.String(36), nullable=False, index=True),
        sa.Column("strategy_key", sa.String(80), nullable=False, index=True),
        sa.Column("strategy_label", sa.String(160), nullable=False),
        sa.Column("strategy_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("chapters_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("chapter_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("text_checksum", sa.String(64), nullable=False, index=True),
        sa.Column("model_run_id", sa.String(36), nullable=True, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="candidate", index=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("uq_opening_candidates_strategy", "opening_candidates", ["experiment_id", "strategy_key"], unique=True)
    op.create_table(
        "reader_evaluations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("experiment_id", sa.String(36), nullable=False, index=True),
        sa.Column("candidate_id", sa.String(36), nullable=False, index=True),
        sa.Column("reviewer_role", sa.String(60), nullable=False, index=True),
        sa.Column("scores_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("findings_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("recommendation", sa.String(40), nullable=False, server_default="revise"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("model_run_id", sa.String(36), nullable=True, index=True),
        sa.Column("checksum", sa.String(64), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_reader_evaluations_candidate_role", "reader_evaluations", ["candidate_id", "reviewer_role"], unique=True)
    op.create_table(
        "style_baselines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("experiment_id", sa.String(36), nullable=False, index=True),
        sa.Column("candidate_id", sa.String(36), nullable=False, index=True),
        sa.Column("story_brief_version_id", sa.String(36), nullable=False, index=True),
        sa.Column("story_brief_checksum", sa.String(64), nullable=False),
        sa.Column("canon_revision", sa.Integer(), nullable=False),
        sa.Column("canon_checksum", sa.String(64), nullable=False),
        sa.Column("sample_checksum", sa.String(64), nullable=False),
        sa.Column("style_rules_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("forbidden_patterns_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("checksum", sa.String(64), nullable=False, index=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="1", index=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_style_baselines_current", "style_baselines", ["project_id"], unique=True, sqlite_where=sa.text("is_current = 1"))


def downgrade() -> None:
    op.drop_index("uq_style_baselines_current", table_name="style_baselines")
    op.drop_table("style_baselines")
    op.drop_index("uq_reader_evaluations_candidate_role", table_name="reader_evaluations")
    op.drop_table("reader_evaluations")
    op.drop_index("uq_opening_candidates_strategy", table_name="opening_candidates")
    op.drop_table("opening_candidates")
    op.drop_table("opening_experiments")
    op.drop_table("story_brief_proposals")
    op.drop_index("uq_story_brief_versions_current", table_name="story_brief_versions")
    op.drop_table("story_brief_versions")
    op.drop_table("ideation_messages")
    op.drop_table("ideation_sessions")
    op.drop_index("uq_story_opportunities_current", table_name="story_opportunities")
    op.drop_table("story_opportunities")
    op.drop_table("research_findings")
    op.drop_table("competitor_profiles")
    op.drop_table("research_evidence")
    op.drop_index("uq_research_source_versions_checksum", table_name="research_source_versions")
    op.drop_table("research_source_versions")
    op.drop_index("uq_research_sources_job_url", table_name="research_sources")
    op.drop_table("research_sources")
    op.drop_index("uq_research_queries_job_fingerprint", table_name="research_queries")
    op.drop_table("research_queries")
    op.drop_index("uq_research_jobs_idempotency", table_name="research_jobs")
    op.drop_table("research_jobs")
    op.drop_index("uq_market_research_briefs_current", table_name="market_research_briefs")
    op.drop_table("market_research_briefs")
