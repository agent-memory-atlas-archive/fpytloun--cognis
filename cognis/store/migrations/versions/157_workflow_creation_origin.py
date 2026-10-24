"""Persist task and schedule creation provenance without legacy inference."""

import sqlalchemy as sa
from alembic import op

revision = "157_workflow_creation_origin"
down_revision = "156_notification_inbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("tasks", "schedules"):
        if "creation_origin" not in {
            column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)
        }:
            op.add_column(table, sa.Column("creation_origin", sa.String(), nullable=True))


def downgrade() -> None:
    for table in ("schedules", "tasks"):
        op.drop_column(table, "creation_origin")
