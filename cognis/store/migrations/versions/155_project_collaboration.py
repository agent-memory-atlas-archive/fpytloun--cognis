"""Project agents, resource visibility, and project roles."""

import sqlalchemy as sa
from alembic import op

revision = "155_project_collaboration"
down_revision = "154_deliverable_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "project_agents" not in tables:
        op.create_table(
            "project_agents",
            sa.Column(
                "project_id",
                sa.String(),
                sa.ForeignKey("projects.project_id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "agent_id",
                sa.String(),
                sa.ForeignKey("agents.agent_id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column(
                "executor_scope",
                sa.String(),
                nullable=False,
                server_default="owner_executor",
            ),
            sa.Column("added_by", sa.String(), sa.ForeignKey("users.email"), nullable=False),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        )
        op.create_index("ix_project_agents_agent", "project_agents", ["agent_id"])
        op.create_index(
            "uq_project_agents_default",
            "project_agents",
            ["agent_id"],
            unique=True,
            sqlite_where=sa.text("is_default"),
            postgresql_where=sa.text("is_default"),
        )
    for table in ("conversations", "tasks"):
        columns = {column["name"] for column in sa.inspect(bind).get_columns(table)}
        if "visibility" not in columns:
            # Existing rows predate project sharing and stay author-only.
            op.add_column(
                table,
                sa.Column("visibility", sa.String(), nullable=False, server_default="private"),
            )
    if "project_grants" in tables:
        op.execute(
            sa.text("UPDATE project_grants SET permission = 'member' WHERE permission = 'use'")
        )


def downgrade() -> None:
    op.execute(sa.text("UPDATE project_grants SET permission = 'use' WHERE permission <> 'use'"))
    op.drop_column("tasks", "visibility")
    op.drop_column("conversations", "visibility")
    op.drop_index("uq_project_agents_default", table_name="project_agents")
    op.drop_index("ix_project_agents_agent", table_name="project_agents")
    op.drop_table("project_agents")
