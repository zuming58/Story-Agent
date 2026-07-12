"""phase four audit integrity fixes"""

from alembic import op


revision = "0005_phase4_audit_fixes"
down_revision = "0004_canon_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Older phase-four builds could briefly create more than one current fact.
    # Keep the newest row current before enforcing the invariant in SQLite.
    op.execute(
        """
        UPDATE state_facts
           SET is_current = 0,
               valid_to = COALESCE(valid_to, updated_at)
         WHERE id IN (
             SELECT id
               FROM (
                   SELECT id,
                          ROW_NUMBER() OVER (
                              PARTITION BY project_id, entity_id, field_path
                              ORDER BY COALESCE(valid_from, created_at) DESC, created_at DESC, id DESC
                          ) AS row_number
                     FROM state_facts
                    WHERE is_current = 1
               ) ranked
              WHERE row_number > 1
         )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_state_facts_current
            ON state_facts(project_id, entity_id, field_path)
         WHERE is_current = 1
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_state_facts_current")
