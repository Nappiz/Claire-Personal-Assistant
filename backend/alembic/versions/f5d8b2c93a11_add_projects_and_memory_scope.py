"""Add projects and scoped memory metadata.

Revision ID: f5d8b2c93a11
Revises: e4c7a1b82f10
Create Date: 2026-09-12 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f5d8b2c93a11"
down_revision: Union[str, Sequence[str], None] = "e4c7a1b82f10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_projects_name", "projects", ["name"], unique=True)
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.String(length=36), nullable=True))
        batch_op.create_index("ix_conversations_project_id", ["project_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_conversations_project_id_projects",
            "projects",
            ["project_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    with op.batch_alter_table("memory_outbox") as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("project_name", sa.String(length=120), nullable=True))
        batch_op.add_column(
            sa.Column("scope", sa.String(length=20), nullable=False, server_default="global")
        )
        batch_op.create_index("ix_memory_outbox_project_id", ["project_id"], unique=False)
        batch_op.create_index("ix_memory_outbox_scope", ["scope"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("memory_outbox") as batch_op:
        batch_op.drop_index("ix_memory_outbox_scope")
        batch_op.drop_index("ix_memory_outbox_project_id")
        batch_op.drop_column("scope")
        batch_op.drop_column("project_name")
        batch_op.drop_column("project_id")
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.drop_constraint("fk_conversations_project_id_projects", type_="foreignkey")
        batch_op.drop_index("ix_conversations_project_id")
        batch_op.drop_column("project_id")
    op.drop_index("ix_projects_name", table_name="projects")
    op.drop_table("projects")
