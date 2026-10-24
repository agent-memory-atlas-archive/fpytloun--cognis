"""Durable video job metadata and spending reservations."""

import sqlalchemy as sa
from alembic import op

revision = "167_video_provider_jobs"
down_revision = "166_document_favorites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Preserve tables already created by startup bootstrap."""
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for name, create in (
        ("video_jobs", _create_jobs),
        ("video_attempts", _create_attempts),
        ("video_budgets", _create_budgets),
        ("video_mutations", _create_mutations),
        ("video_transfers", _create_transfers),
    ):
        if name not in tables:
            create()


def _create_jobs() -> None:
    op.create_table(
        "video_jobs",
        sa.Column("job_id", sa.String(), primary_key=True),
        *[
            sa.Column(name, sa.String(), nullable=False)
            for name in (
                "owner_email",
                "agent_id",
                "conversation_id",
                "idempotency_key",
                "request_hash",
                "request_artifact_id",
                "operation",
                "provider_id",
                "model",
                "status",
                "attempt_id",
                "cost_status",
                "budget_day",
            )
        ],
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("binding", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("estimated_microusd", sa.BigInteger(), nullable=False),
        sa.Column("actual_microusd", sa.BigInteger(), nullable=True),
        sa.Column("outputs", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("notified", sa.Boolean(), nullable=False),
        *[
            sa.Column(name, sa.TIMESTAMP(timezone=True), nullable=False)
            for name in ("next_poll_at", "created_at", "updated_at")
        ],
        sa.UniqueConstraint(
            "owner_email", "conversation_id", "idempotency_key", name="uq_video_request"
        ),
    )
    op.create_index("ix_video_due", "video_jobs", ["status", "next_poll_at"])
    op.create_index(
        "ix_video_owner_conversation",
        "video_jobs",
        ["owner_email", "conversation_id", "created_at"],
    )


def _create_attempts() -> None:
    op.create_table(
        "video_attempts",
        sa.Column("attempt_id", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String(), sa.ForeignKey("video_jobs.job_id"), nullable=False),
        sa.Column("dispatched", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )


def _create_budgets() -> None:
    op.create_table(
        "video_budgets",
        sa.Column("owner_email", sa.String(), primary_key=True),
        sa.Column("day", sa.String(), primary_key=True),
        sa.Column("exposure_microusd", sa.BigInteger(), nullable=False),
    )


def _create_mutations() -> None:
    op.create_table(
        "video_mutations",
        sa.Column("job_id", sa.String(), sa.ForeignKey("video_jobs.job_id"), primary_key=True),
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False),
    )


def _create_transfers() -> None:
    op.create_table(
        "video_transfers",
        sa.Column("token_hash", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String(), sa.ForeignKey("video_jobs.job_id"), nullable=False),
        sa.Column("attempt_id", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("max_bytes", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("artifact_id", sa.String(), nullable=True),
    )
    op.create_index("ix_video_transfers_job_id", "video_transfers", ["job_id"])


def downgrade() -> None:
    op.drop_table("video_transfers")
    op.drop_table("video_mutations")
    op.drop_table("video_budgets")
    op.drop_table("video_attempts")
    op.drop_table("video_jobs")
