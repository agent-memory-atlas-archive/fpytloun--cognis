"""Persist optional task escalation timeout."""

import sqlalchemy as sa
from alembic import op

revision = "151_task_escalation_timeout"
down_revision = "150_managed_delegation_depth_limit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("tasks")}
    if "escalation_timeout_seconds" not in columns:
        op.add_column("tasks", sa.Column("escalation_timeout_seconds", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "escalation_timeout_seconds")
