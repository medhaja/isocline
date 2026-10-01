"""Isocline schema baseline.

Creates every table from the ORM metadata, the pgvector extension and HNSW index for knowledge retrieval, and a
PostgreSQL trigger that keeps the audit log append-only. Later schema changes are new, append-only revisions.

Revision ID: 0001_initial
Revises:
"""
from alembic import op

from isocline.db.models import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

APPEND_ONLY_FN = """
CREATE OR REPLACE FUNCTION isocline_append_only() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END; $$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    bind = op.get_bind()
    pg = bind.dialect.name == "postgresql"
    if pg:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind)
    if pg:
        op.execute("CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding ON document_chunks "
                   "USING hnsw (embedding vector_cosine_ops)")
        op.execute(APPEND_ONLY_FN)
        op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
        op.execute("CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events "
                   "FOR EACH ROW EXECUTE FUNCTION isocline_append_only()")


def downgrade() -> None:
    # runs <-> checkpoints reference each other, so a dependency-ordered drop_all() cannot sort the tables.
    # Drop in reverse creation order instead; PostgreSQL's CASCADE removes the cross-table constraints.
    bind = op.get_bind()
    pg = bind.dialect.name == "postgresql"
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # sorted_tables warns about the cycle; the order below does not rely on it
        tables = list(reversed(Base.metadata.sorted_tables))
    for table in tables:
        op.execute(f'DROP TABLE IF EXISTS "{table.name}"' + (" CASCADE" if pg else ""))
    if pg:
        op.execute("DROP FUNCTION IF EXISTS isocline_append_only() CASCADE")
