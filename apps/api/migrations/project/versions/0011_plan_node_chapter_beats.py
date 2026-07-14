"""add chapter-level beats to planning windows"""

from alembic import op
import sqlalchemy as sa


revision = "0011_plan_node_chapter_beats"
down_revision = "0010_trial_ready_workbench"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "plan_nodes",
        sa.Column("chapter_beats_json", sa.Text(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("plan_nodes", "chapter_beats_json")
