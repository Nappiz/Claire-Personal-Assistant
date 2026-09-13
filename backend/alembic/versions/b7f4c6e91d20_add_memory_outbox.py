"""Add durable memory outbox.

Revision ID: b7f4c6e91d20
Revises: 31b2b6e62459
Create Date: 2026-09-09 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7f4c6e91d20"
down_revision: Union[str, Sequence[str], None] = "31b2b6e62459"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memory_outbox",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("user_message_id", sa.String(length=36), nullable=True),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("assistant_response", sa.Text(), nullable=False),
        sa.Column("session_history", sa.JSON(), nullable=False),
        sa.Column("neo4j_context", sa.JSON(), nullable=False),
        sa.Column("extracted_knowledge", sa.JSON(), nullable=True),
        sa.Column("vector_saved", sa.Boolean(), nullable=False),
        sa.Column("extraction_completed", sa.Boolean(), nullable=False),
        sa.Column("graph_saved", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_outbox_conversation_id", "memory_outbox", ["conversation_id"])
    op.create_index("ix_memory_outbox_user_message_id", "memory_outbox", ["user_message_id"])
    op.create_index("ix_memory_outbox_status", "memory_outbox", ["status"])
    op.create_index("ix_memory_outbox_next_retry_at", "memory_outbox", ["next_retry_at"])


def downgrade() -> None:
    op.drop_index("ix_memory_outbox_next_retry_at", table_name="memory_outbox")
    op.drop_index("ix_memory_outbox_status", table_name="memory_outbox")
    op.drop_index("ix_memory_outbox_user_message_id", table_name="memory_outbox")
    op.drop_index("ix_memory_outbox_conversation_id", table_name="memory_outbox")
    op.drop_table("memory_outbox")
