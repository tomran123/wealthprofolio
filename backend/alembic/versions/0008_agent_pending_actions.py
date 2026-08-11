"""add server-side agent mutation confirmations

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-23
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_pending_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assistant_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_messages.id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
        ),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("tool_calls_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("result_trace_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_pending_actions_session_id", "agent_pending_actions", ["session_id"])
    op.create_index("ix_agent_pending_actions_status", "agent_pending_actions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_agent_pending_actions_status", table_name="agent_pending_actions")
    op.drop_index("ix_agent_pending_actions_session_id", table_name="agent_pending_actions")
    op.drop_table("agent_pending_actions")
