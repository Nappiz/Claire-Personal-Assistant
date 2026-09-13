"""Record provider attempts and durable incomplete answer metadata.

Revision ID: c7e9a210d643
Revises: a9c2f604d812
"""
from alembic import op
import sqlalchemy as sa

revision = "c7e9a210d643"
down_revision = "a9c2f604d812"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("response_status", sa.String(20), nullable=False, server_default="complete"))
        batch.add_column(sa.Column("finish_reason", sa.String(50), nullable=True))
    op.create_table(
        "ai_invocations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=True),
        sa.Column("turn_id", sa.String(36), nullable=True),
        sa.Column("job_id", sa.String(36), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("job_attempt", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("provider_request_id", sa.String(255), nullable=True),
        sa.Column("response_id", sa.String(255), nullable=True),
        sa.Column("finish_reason", sa.String(50), nullable=True),
        sa.Column("error_type", sa.String(100), nullable=True),
        sa.Column("usage_available", sa.Boolean(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("usage_details", sa.JSON(), nullable=True),
        sa.Column("total_cost", sa.Float(), nullable=True),
    )
    for field in ("purpose", "conversation_id", "turn_id", "job_id", "status"):
        op.create_index(f"ix_ai_invocations_{field}", "ai_invocations", [field])


def downgrade():
    op.drop_table("ai_invocations")
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("finish_reason")
        batch.drop_column("response_status")
