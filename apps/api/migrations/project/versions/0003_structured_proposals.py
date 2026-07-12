"""structured proposal diagnostics"""
from alembic import op
import sqlalchemy as sa

revision = "0003_structured_proposals"
down_revision = "0002_model_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("change_operations", sa.Column("before_json", sa.Text(), nullable=True))
    op.add_column("change_operations", sa.Column("after_json", sa.Text(), nullable=True))
    op.add_column("model_runs", sa.Column("diagnostic_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("model_runs", "diagnostic_json")
    op.drop_column("change_operations", "after_json")
    op.drop_column("change_operations", "before_json")
