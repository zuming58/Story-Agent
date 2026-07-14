"""export publishing foundation"""

from alembic import op
import sqlalchemy as sa


revision = "0013_export_publishing_foundation"
down_revision = "0012_story_architecture"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "export_profiles",
        sa.Column("project_id", sa.String(36), primary_key=True),
        sa.Column("default_formats_json", sa.Text(), nullable=False, server_default='["txt","markdown","docx","epub"]'),
        sa.Column("book_title", sa.String(240), nullable=False, server_default=""),
        sa.Column("author_name", sa.String(160), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("chapter_title_template", sa.String(160), nullable=False, server_default="第{chapter}章 {title}"),
        sa.Column("include_quality_summary", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "export_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("mode", sa.String(20), nullable=False, index=True),
        sa.Column("chapter_start", sa.Integer(), nullable=False),
        sa.Column("chapter_end", sa.Integer(), nullable=False),
        sa.Column("formats_json", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, index=True),
        sa.Column("frozen_manifest_json", sa.Text(), nullable=False),
        sa.Column("readiness_json", sa.Text(), nullable=False),
        sa.Column("stop_reason", sa.String(120), nullable=True),
        sa.Column("diagnostic_json", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_export_jobs_idempotency",
        "export_jobs",
        ["project_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL AND idempotency_key != ''"),
    )
    op.create_table(
        "export_job_chapters",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("export_job_id", sa.String(36), nullable=False, index=True),
        sa.Column("chapter_number", sa.Integer(), nullable=False, index=True),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("chapter_title", sa.String(240), nullable=False, server_default=""),
        sa.Column("chapter_commit_id", sa.String(36), nullable=True, index=True),
        sa.Column("approved_draft_id", sa.String(36), nullable=True, index=True),
        sa.Column("source_version_id", sa.String(36), nullable=True, index=True),
        sa.Column("state_snapshot_id", sa.String(36), nullable=True, index=True),
        sa.Column("commit_revision", sa.Integer(), nullable=True),
        sa.Column("source_revision", sa.Integer(), nullable=True),
        sa.Column("draft_revision", sa.Integer(), nullable=True),
        sa.Column("snapshot_revision", sa.Integer(), nullable=True),
        sa.Column("commit_checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("draft_checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("source_checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("quality_summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("issue_summary_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("content_markdown", sa.Text(), nullable=False, server_default=""),
        sa.Column("missing", sa.Boolean(), nullable=False, server_default=sa.text("0"), index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("export_job_id", "chapter_number", name="uq_export_job_chapters_job_chapter"),
    )
    op.create_table(
        "export_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("export_job_id", sa.String(36), nullable=False, index=True),
        sa.Column("format", sa.String(20), nullable=False, index=True),
        sa.Column("relative_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("mime_type", sa.String(120), nullable=False, server_default="application/octet-stream"),
        sa.Column("file_name", sa.String(240), nullable=False, server_default=""),
        sa.Column("sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("manifest_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("1"), index=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_export_artifacts_current",
        "export_artifacts",
        ["export_job_id", "format"],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
    )
    op.create_table(
        "publication_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("export_job_id", sa.String(36), nullable=False, index=True),
        sa.Column("artifact_id", sa.String(36), nullable=False, index=True),
        sa.Column("platform", sa.String(120), nullable=False, index=True),
        sa.Column("external_work_ref", sa.String(240), nullable=False, server_default=""),
        sa.Column("external_chapter_ref", sa.String(240), nullable=False, server_default=""),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("publication_records")
    op.drop_index("uq_export_artifacts_current", table_name="export_artifacts")
    op.drop_table("export_artifacts")
    op.drop_table("export_job_chapters")
    op.drop_index("uq_export_jobs_idempotency", table_name="export_jobs")
    op.drop_table("export_jobs")
    op.drop_table("export_profiles")
