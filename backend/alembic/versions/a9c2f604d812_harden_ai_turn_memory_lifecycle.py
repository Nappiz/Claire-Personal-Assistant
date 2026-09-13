"""Harden AI turn, memory lease, deletion, and summary lifecycle.

Revision ID: a9c2f604d812
Revises: f5d8b2c93a11
Create Date: 2026-09-12 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "a9c2f604d812"
down_revision: Union[str, Sequence[str], None] = "f5d8b2c93a11"
branch_labels = None
depends_on = None

def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("summary_version", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("summary_through_sequence", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("summary_pending", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("next_turn_sequence", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("active_turn_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("active_turn_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_conversations_active_turn_id", ["active_turn_id"])
        batch.create_index("ix_conversations_active_turn_expires_at", ["active_turn_expires_at"])
        batch.create_index("ix_conversations_deleted_at", ["deleted_at"])
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("turn_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("turn_sequence", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("memory_status", sa.String(20), nullable=False, server_default="active"))
        batch.create_index("ix_messages_turn_id", ["turn_id"])
        batch.create_index("ix_messages_turn_sequence", ["turn_sequence"])
        batch.create_index("ix_messages_memory_status", ["memory_status"])
        batch.create_unique_constraint("uq_message_turn_role", ["conversation_id", "turn_id", "role"])
    with op.batch_alter_table("memory_outbox") as batch:
        batch.add_column(sa.Column("lease_token", sa.String(36), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("event_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()))
        batch.create_index("ix_memory_outbox_lease_token", ["lease_token"])
        batch.create_index("ix_memory_outbox_lease_expires_at", ["lease_expires_at"])
        batch.create_index("ix_memory_outbox_event_at", ["event_at"])
    op.execute("UPDATE memory_outbox SET event_at = created_at")

def downgrade() -> None:
    with op.batch_alter_table("memory_outbox") as batch:
        batch.drop_index("ix_memory_outbox_event_at")
        batch.drop_index("ix_memory_outbox_lease_expires_at")
        batch.drop_index("ix_memory_outbox_lease_token")
        batch.drop_column("event_at")
        batch.drop_column("lease_expires_at")
        batch.drop_column("lease_token")
    with op.batch_alter_table("messages") as batch:
        batch.drop_constraint("uq_message_turn_role", type_="unique")
        batch.drop_index("ix_messages_memory_status")
        batch.drop_index("ix_messages_turn_sequence")
        batch.drop_index("ix_messages_turn_id")
        batch.drop_column("turn_sequence")
        batch.drop_column("memory_status")
        batch.drop_column("turn_id")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_index("ix_conversations_deleted_at")
        batch.drop_index("ix_conversations_active_turn_id")
        batch.drop_index("ix_conversations_active_turn_expires_at")
        for column in ("deleted_at", "active_turn_expires_at", "active_turn_id", "next_turn_sequence", "summary_pending", "summary_through_sequence", "summary_version"):
            batch.drop_column(column)
