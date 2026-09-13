"""Add persistent assistant error diagnostics.

Revision ID: d8a2c194f301
Revises: b7f4c6e91d20
Create Date: 2026-09-11 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8a2c194f301"
down_revision: Union[str, Sequence[str], None] = "b7f4c6e91d20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.add_column(
            sa.Column(
                "message_type",
                sa.String(length=30),
                nullable=False,
                server_default="normal",
            )
        )
        batch_op.add_column(sa.Column("error_details", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_column("error_details")
        batch_op.drop_column("message_type")

