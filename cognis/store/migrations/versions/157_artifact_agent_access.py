"""Agent-owned artifacts and explicit content read grants."""

from __future__ import annotations

from alembic import op

from cognis.store.artifact_access_schema import ensure_artifact_access_schema

revision = "157_artifact_agent_access"
down_revision = "156_notification_inbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_artifact_access_schema(op.get_bind())


def downgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.drop_column("artifact_scope_id")
    op.drop_table("artifact_grants")
    for table, columns in (
        ("artifacts", ("owner_agent_id",)),
        ("deliverables", ("owner_agent_id", "owner_email")),
    ):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_agent_owner")
            for column in columns:
                batch.drop_column(column)
