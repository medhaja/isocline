"""Model pricing: record who owns each row's prices (shipped catalog, live price feed, or an administrator).

Idempotent: databases created after this change already have the column (0001 builds the current schema).
Existing rows become "catalog", so the live price feed may update them; prices an administrator set before this
upgrade should be re-entered once (Settings -> Models) to mark them as administrator-owned.

Revision ID: 0003_model_pricing_source
Revises: 0002_remove_deployments
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_model_pricing_source"
down_revision = "0002_remove_deployments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "model_pricing" in insp.get_table_names() and "source" not in {c["name"] for c in insp.get_columns("model_pricing")}:
        with op.batch_alter_table("model_pricing") as b:  # batch mode also works on SQLite
            b.add_column(sa.Column("source", sa.String(16), nullable=False, server_default="catalog"))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "source" in {c["name"] for c in insp.get_columns("model_pricing")}:
        with op.batch_alter_table("model_pricing") as b:
            b.drop_column("source")
