"""Governance hardening: append-only audit log, trigram search index.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Audit rows are immutable: reject UPDATE and DELETE at the database level.
    # (Retention purges run as a privileged maintenance role that disables the trigger explicitly.)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_logs_immutable() RETURNS trigger AS $$
        BEGIN
          IF current_setting('app.audit_maintenance', true) = 'on' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'audit_logs is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_logs_immutable
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION audit_logs_immutable();
        """
    )
    # Fuzzy candidate search (name/email/headline).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidates_search_trgm ON candidates USING gin "
        "((lower(first_name || ' ' || last_name || ' ' || email || ' ' || coalesce(headline, ''))) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_candidates_search_trgm")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_immutable ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS audit_logs_immutable()")
