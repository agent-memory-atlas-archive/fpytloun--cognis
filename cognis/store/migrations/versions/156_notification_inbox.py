"""Add the user-owned informational notification inbox."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "156_notification_inbox"
down_revision = "155_project_collaboration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "inbox_notifications" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "inbox_notifications",
        sa.Column("notification_id", sa.String(), primary_key=True),
        sa.Column(
            "user_email",
            sa.String(),
            sa.ForeignKey("users.email", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("href", sa.String(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("read_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_inbox_user_created",
        "inbox_notifications",
        ["user_email", "created_at", "notification_id"],
    )
    op.create_index("ix_inbox_user_read", "inbox_notifications", ["user_email", "read_at"])


def downgrade() -> None:
    if "inbox_notifications" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("inbox_notifications")
