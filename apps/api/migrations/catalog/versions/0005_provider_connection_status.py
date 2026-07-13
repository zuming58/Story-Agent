"""persist model provider connection test status"""

from alembic import op
import sqlalchemy as sa


revision = "0005_provider_connection_status"
down_revision = "0004_model_pricing_guards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_providers", sa.Column("last_test_status", sa.String(40), nullable=True))
    op.add_column("model_providers", sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("model_providers", "last_tested_at")
    op.drop_column("model_providers", "last_test_status")
