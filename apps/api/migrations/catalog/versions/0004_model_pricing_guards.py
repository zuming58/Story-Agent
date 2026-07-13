"""enforce non-negative model prices"""

from alembic import op


revision = "0004_model_pricing_guards"
down_revision = "0003_model_pricing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TRIGGER ck_model_configs_price_insert
        BEFORE INSERT ON model_configs
        WHEN NEW.input_price_per_million < 0 OR NEW.output_price_per_million < 0
        BEGIN
            SELECT RAISE(ABORT, 'model prices must be non-negative');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER ck_model_configs_price_update
        BEFORE UPDATE OF input_price_per_million, output_price_per_million ON model_configs
        WHEN NEW.input_price_per_million < 0 OR NEW.output_price_per_million < 0
        BEGIN
            SELECT RAISE(ABORT, 'model prices must be non-negative');
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS ck_model_configs_price_update")
    op.execute("DROP TRIGGER IF EXISTS ck_model_configs_price_insert")
