import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AgentChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    session_id: uuid.UUID | None = None


class ExtractedLineItem(BaseModel):
    instrument: str | None = None
    symbol: str | None = None
    quantity: str | None = None
    price: str | None = None
    amount: str | None = None
    currency: str | None = None
    date: str | None = None
    transaction_type: str | None = None
    fee: str | None = None
    account: str | None = None
    note: str | None = None


class ExtractedDocumentData(BaseModel):
    institution: str | None = None
    account: str | None = None
    document_type: str | None = None
    items: list[ExtractedLineItem] = []
    warnings: list[str] = []


class AgentPendingActionRead(BaseModel):
    id: uuid.UUID
    created_at: datetime
    status: Literal["pending", "executing", "confirmed", "cancelled", "failed", "stale"]
    tool_calls: list[dict[str, Any]]
    result_trace: list[dict[str, Any]] = []
    error: str | None = None
    resolved_at: datetime | None = None


class AgentTurnResult(BaseModel):
    session_id: uuid.UUID
    assistant_message: str
    tool_call_trace: list[dict[str, Any]]
    extracted_documents: list[dict[str, Any]] = []
    pending_action: AgentPendingActionRead | None = None


class AgentMessageRead(BaseModel):
    id: uuid.UUID
    created_at: datetime
    role: str
    content: str
    attachments: list[dict[str, Any]]
    tool_trace: list[dict[str, Any]]
    pending_action: AgentPendingActionRead | None = None


class AgentSessionRead(BaseModel):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    title: str
    message_count: int


class AgentSessionDetail(AgentSessionRead):
    messages: list[AgentMessageRead]


class AgentOperationLogRead(BaseModel):
    id: uuid.UUID
    created_at: datetime
    session_id: uuid.UUID
    turn_index: int
    operation_type: str
    user_message: str
    description: str
    tool_calls: list[dict[str, Any]]
    change_summary: dict[str, int]
    event_ids: list[uuid.UUID] = []
    summary: dict[str, Any] = {}
    is_undoable: bool = False
    is_undone: bool
    undone_at: datetime | None
    linked_to_id: uuid.UUID | None


class AgentOperationLogPage(BaseModel):
    items: list[AgentOperationLogRead]
    total: int
    offset: int
    limit: int


class UndoResult(BaseModel):
    ok: bool
    log_id: uuid.UUID
    undone_at: datetime
