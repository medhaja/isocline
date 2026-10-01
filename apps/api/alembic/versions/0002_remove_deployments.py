"""Remove API deployments and environments (dev/staging/production promotion).

Drops their tables and the columns that referenced them. Idempotent: on databases created after this change the
objects never existed and nothing happens. Data in these tables is discarded.

Revision ID: 0002_remove_deployments
Revises: 0001_initial
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_remove_deployments"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

COLUMNS = [("runs", "deployment_id"), ("runs", "environment_id"), ("triggers", "environment_id"),
           ("mcp_servers", "environment_id"), ("drift_events", "environment_id"), ("drift_events", "deployment_id")]
TABLES = ["gate_results", "deployment_gates", "environment_releases", "environment_configs", "deployment_api_keys",
          "deployments", "environments"]  # children first


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())
    for table, column in COLUMNS:
        if table in existing and column in {c["name"] for c in insp.get_columns(table)}:
            with op.batch_alter_table(table) as b:  # batch mode also works on SQLite
                b.drop_column(column)
    for table in TABLES:
        if table in existing:
            op.drop_table(table)


def downgrade() -> None:
    # Removed features are not restored.
    pass
