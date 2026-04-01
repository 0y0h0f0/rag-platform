"""version 5 reliability fields

Revision ID: 20260401_0002
Revises: 20260401_0001
Create Date: 2026-04-01 20:40:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260401_0002"
down_revision = "20260401_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    document_columns = {column["name"] for column in inspector.get_columns("documents")}
    document_indexes = {index["name"] for index in inspector.get_indexes("documents")}
    task_columns = {column["name"] for column in inspector.get_columns("tasks")}

    if "content_hash" not in document_columns:
        op.add_column("documents", sa.Column("content_hash", sa.String(length=64), nullable=True))
        op.execute("UPDATE documents SET content_hash = '' WHERE content_hash IS NULL")

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("documents") as batch_op:
            batch_op.alter_column("content_hash", existing_type=sa.String(length=64), nullable=False)
    else:
        op.alter_column("documents", "content_hash", existing_type=sa.String(length=64), nullable=False)

    if "ix_documents_content_hash" not in document_indexes:
        op.create_index("ix_documents_content_hash", "documents", ["content_hash"])

    if "retry_count" not in task_columns:
        op.add_column("tasks", sa.Column("retry_count", sa.Integer(), nullable=True, server_default="0"))
        op.execute("UPDATE tasks SET retry_count = 0 WHERE retry_count IS NULL")

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("tasks") as batch_op:
            batch_op.alter_column("retry_count", existing_type=sa.Integer(), nullable=False, server_default="0")
    else:
        op.alter_column("tasks", "retry_count", existing_type=sa.Integer(), nullable=False, server_default="0")


def downgrade() -> None:
    op.drop_column("tasks", "retry_count")
    op.drop_index("ix_documents_content_hash", table_name="documents")
    op.drop_column("documents", "content_hash")
