"""initial catalog schema"""
from alembic import op
import sqlalchemy as sa

revision = "0001_catalog"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("mode", sa.String(40), nullable=False),
        sa.Column("folder_path", sa.Text(), nullable=False, unique=True),
        sa.Column("current_chapter", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_chapters", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_opened_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(120), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_table("projects")
