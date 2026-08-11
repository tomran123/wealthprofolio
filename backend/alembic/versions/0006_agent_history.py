"""add agent sessions, messages, and undoable operation logs

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-21
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False, server_default="New conversation"),
    )

    op.create_table(
        "agent_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("attachments_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("tool_trace_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.create_index("ix_agent_messages_created_at", "agent_messages", ["created_at"])
    op.create_index("ix_agent_messages_session_id", "agent_messages", ["session_id"])

    op.create_table(
        "agent_operation_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("turn_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("operation_type", sa.String(length=30), nullable=False, server_default="tool_call"),
        sa.Column("description", sa.String(length=300), nullable=False, server_default="Agent operation"),
        sa.Column("tool_calls_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("before_state_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("after_state_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_undone", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("linked_to_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["linked_to_id"],
            ["agent_operation_logs.id"],
            name="fk_agent_operation_logs_linked_to_id",
            ondelete="SET NULL",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    op.create_index("ix_agent_operation_logs_created_at", "agent_operation_logs", ["created_at"])
    op.create_index("ix_agent_operation_logs_session_id", "agent_operation_logs", ["session_id"])
    op.create_index("ix_agent_operation_logs_is_undone", "agent_operation_logs", ["is_undone"])


def downgrade() -> None:
    op.drop_index("ix_agent_operation_logs_is_undone", table_name="agent_operation_logs")
    op.drop_index("ix_agent_operation_logs_session_id", table_name="agent_operation_logs")
    op.drop_index("ix_agent_operation_logs_created_at", table_name="agent_operation_logs")
    op.drop_table("agent_operation_logs")
    op.drop_index("ix_agent_messages_session_id", table_name="agent_messages")
    op.drop_index("ix_agent_messages_created_at", table_name="agent_messages")
    op.drop_table("agent_messages")
    op.drop_table("agent_sessions")
