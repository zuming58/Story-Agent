"""model pricing for automation cost controls"""

from alembic import op
import sqlalchemy as sa


revision = "0003_model_pricing"
down_revision = "0002_model_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_configs", sa.Column("input_price_per_million", sa.Float(), nullable=True))
    op.add_column("model_configs", sa.Column("output_price_per_million", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("model_configs", "output_price_per_million")
    op.drop_column("model_configs", "input_price_per_million")
