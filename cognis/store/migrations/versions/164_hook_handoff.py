"""Fork hook outcome pointers and serialization."""

from alembic import op

from cognis.store.hook_schema import ensure_hook_handoff

revision = "164_hook_handoff"
down_revision = "163_hook_activation_boundary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_hook_handoff(op.get_bind())


def downgrade() -> None:
    op.drop_index("ix_hook_child", table_name="agent_hook_runs")
    op.drop_index("ix_hook_run_scope", table_name="agent_hook_runs")
    op.drop_index("uq_hook_fork_slot", table_name="agent_hook_runs")
    with op.batch_alter_table("agent_hook_runs") as batch:
        batch.drop_column("fork_slot")
        batch.drop_column("handoff")
