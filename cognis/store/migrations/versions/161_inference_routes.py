"""Named inference routes and durable session affinity; availability lives in Redis."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "161_inference_routes"
down_revision = "160_content_revisions_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Bootstrap creates the same new tables through Base.metadata.create_all."""
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "inference_routes" not in tables:
        _create_routes()
    if "inference_bindings" not in tables:
        _create_bindings()


def _create_routes() -> None:
    op.create_table(
        "inference_routes",
        sa.Column("route_id", sa.String(), primary_key=True),
        sa.Column("owner_email", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_email", "name", name="uq_inference_routes_owner_name"),
    )


def _create_bindings() -> None:
    op.create_table(
        "inference_bindings",
        sa.Column("binding_key", sa.String(64), primary_key=True),
        sa.Column("owner_email", sa.String(), nullable=False),
        sa.Column("reference", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("target", sa.JSON(), nullable=True),
        sa.Column("pending_target", sa.JSON(), nullable=True),
        sa.Column("claim_token", sa.String(), nullable=True),
        sa.Column("claim_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index("ix_inference_bindings_expires", "inference_bindings", ["expires_at"])


def downgrade() -> None:
    """Preserve legacy role routing and concrete provider configuration."""
    op.drop_table("inference_bindings")
    op.drop_table("inference_routes")
