import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, FamilyScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class AgentSession(UUIDPrimaryKeyMixin, TimestampMixin, FamilyScopedMixin, Base):
    __tablename__ = "agent_sessions"

    title: Mapped[str] = mapped_column(String(160), nullable=False, default="New conversation")

    messages: Mapped[list["AgentMessage"]] = relationship(
        "AgentMessage", back_populates="session", cascade="all, delete-orphan"
    )
    operation_logs: Mapped[list["AgentOperationLog"]] = relationship(
        "AgentOperationLog",
        back_populates="session",
        cascade="all, delete-orphan",
        foreign_keys="AgentOperationLog.session_id",
    )
    pending_actions: Mapped[list["AgentPendingAction"]] = relationship(
        "AgentPendingAction",
        back_populates="session",
        cascade="all, delete-orphan",
        foreign_keys="AgentPendingAction.session_id",
    )


class AgentMessage(UUIDPrimaryKeyMixin, FamilyScopedMixin, Base):
    __tablename__ = "agent_messages"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    attachments_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    tool_trace_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    session: Mapped[AgentSession] = relationship("AgentSession", back_populates="messages")
    pending_action: Mapped["AgentPendingAction | None"] = relationship(
        "AgentPendingAction",
        back_populates="assistant_message",
        uselist=False,
        foreign_keys="AgentPendingAction.assistant_message_id",
    )


class AgentPendingAction(UUIDPrimaryKeyMixin, TimestampMixin, FamilyScopedMixin, Base):
    """A server-side mutation plan waiting for an explicit UI confirmation."""

    __tablename__ = "agent_pending_actions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assistant_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_messages.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_versions_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    tool_calls_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    result_trace_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped[AgentSession] = relationship(
        "AgentSession",
        back_populates="pending_actions",
        foreign_keys=[session_id],
    )
    assistant_message: Mapped[AgentMessage | None] = relationship(
        "AgentMessage",
        back_populates="pending_action",
        foreign_keys=[assistant_message_id],
    )


class AgentOperationLog(UUIDPrimaryKeyMixin, FamilyScopedMixin, Base):
    __tablename__ = "agent_operation_logs"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    operation_type: Mapped[str] = mapped_column(String(30), nullable=False, default="tool_call")
    description: Mapped[str] = mapped_column(String(300), nullable=False, default="Agent operation")
    tool_calls_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    before_state_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    after_state_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    event_ids_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    summary_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_undone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    linked_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "agent_operation_logs.id",
            ondelete="SET NULL",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=True,
    )

    session: Mapped[AgentSession] = relationship(
        "AgentSession", back_populates="operation_logs", foreign_keys=[session_id]
    )
