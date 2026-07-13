"""track the active candidate draft for each chapter job"""

from alembic import op
import sqlalchemy as sa


revision = "0007_chapter_draft_current"
down_revision = "0006_chapter_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chapter_drafts",
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        """
        UPDATE chapter_drafts
        SET is_current = 1
        WHERE id IN (
            SELECT newest.id
            FROM chapter_drafts AS newest
            WHERE newest.version_number = (
                SELECT MAX(candidate.version_number)
                FROM chapter_drafts AS candidate
                WHERE candidate.chapter_job_id = newest.chapter_job_id
            )
        )
        """
    )
    op.create_index("ix_chapter_drafts_is_current", "chapter_drafts", ["is_current"])
    op.create_index(
        "uq_chapter_drafts_current",
        "chapter_drafts",
        ["chapter_job_id"],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
    )


def downgrade() -> None:
    op.drop_index("uq_chapter_drafts_current", table_name="chapter_drafts")
    op.drop_index("ix_chapter_drafts_is_current", table_name="chapter_drafts")
    op.drop_column("chapter_drafts", "is_current")
