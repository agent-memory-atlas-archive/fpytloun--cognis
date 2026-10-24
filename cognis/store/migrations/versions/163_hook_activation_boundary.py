"""Make idle hook activation prospective, including existing assignments at rollout."""

from __future__ import annotations

from alembic import op

from cognis.store.hook_schema import ensure_hook_activation_boundary

revision = "163_hook_activation_boundary"
down_revision = "162_agent_hooks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Install the same idempotent activation fence as startup bootstrap."""
    ensure_hook_activation_boundary(op.get_bind())


def downgrade() -> None:
    """Remove activation metadata without changing conversations or runs."""
    op.drop_column("agent_hook_assignments", "activated_at")
