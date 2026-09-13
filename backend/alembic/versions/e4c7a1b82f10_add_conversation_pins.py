"""Add conversation pin state.

Revision ID: e4c7a1b82f10
Revises: d8a2c194f301
Create Date: 2026-09-12 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4c7a1b82f10"
down_revision: Union[str, Sequence[str], None] = "d8a2c194f301"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_pinned",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.drop_column("pinned_at")
        batch_op.drop_column("is_pinned")

