"""trial-ready automation run overrides"""

from alembic import op
import sqlalchemy as sa


revision = "0010_trial_ready_workbench"
down_revision = "0009_automation_audit_fixes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("automation_runs", sa.Column("requested_chapter_count", sa.Integer(), nullable=True))
    op.execute(
        """
        CREATE TRIGGER ck_automation_runs_requested_count_insert
        BEFORE INSERT ON automation_runs
        WHEN NEW.requested_chapter_count IS NOT NULL AND NEW.requested_chapter_count NOT IN (1, 3, 5)
        BEGIN
            SELECT RAISE(ABORT, 'requested chapter count must be 1, 3, or 5');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER ck_automation_runs_requested_count_update
        BEFORE UPDATE OF requested_chapter_count ON automation_runs
        WHEN NEW.requested_chapter_count IS NOT NULL AND NEW.requested_chapter_count NOT IN (1, 3, 5)
        BEGIN
            SELECT RAISE(ABORT, 'requested chapter count must be 1, 3, or 5');
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS ck_automation_runs_requested_count_update")
    op.execute("DROP TRIGGER IF EXISTS ck_automation_runs_requested_count_insert")
    op.drop_column("automation_runs", "requested_chapter_count")
