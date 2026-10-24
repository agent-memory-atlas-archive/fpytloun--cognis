"""Shared provider monitoring snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "152_provider_monitor"
down_revision = "151_task_escalation_timeout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "provider_monitor_snapshots" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "provider_monitor_snapshots",
        sa.Column(
            "provider_id",
            sa.String(),
            sa.ForeignKey("llm_providers.provider_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("checked_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("next_refresh_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("health_checked_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("health", sa.JSON(), nullable=False),
        sa.Column("usage", sa.JSON()),
        sa.Column("error", sa.String()),
        sa.Column("failures", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("provider_monitor_snapshots")
