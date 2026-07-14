"""distinguish demo and standard projects"""

from alembic import op
import sqlalchemy as sa


revision = "0006_project_kind"
down_revision = "0005_provider_connection_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("project_kind", sa.String(20), nullable=False, server_default="standard"))
    op.execute("UPDATE projects SET project_kind = 'demo' WHERE title = '夜巡人' AND current_chapter >= 36")
    op.create_index("ix_projects_project_kind", "projects", ["project_kind"])


def downgrade() -> None:
    op.drop_index("ix_projects_project_kind", table_name="projects")
    op.drop_column("projects", "project_kind")
