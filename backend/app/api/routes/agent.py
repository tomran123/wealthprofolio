import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.agent import (
    cancel_pending_action,
    confirm_pending_action,
    pending_action_schema,
    run_agent_turn,
)
from app.agent.extraction import ALLOWED_AGENT_MIME_TYPES, UploadedDocument
from app.agent.state import summarize_diff
from app.api.deps import get_current_user, get_db
from app.core.config import get_settings
from app.models import AgentOperationLog, AgentPendingAction, AgentSession
from app.schemas.agent import (
    AgentChatRequest,
    AgentMessageRead,
    AgentOperationLogPage,
    AgentOperationLogRead,
    AgentSessionDetail,
    AgentSessionRead,
    AgentTurnResult,
    ChatMessage,
    UndoResult,
)
from app.services import agent_history_service, undo_service

router = APIRouter(prefix="/api/agent", tags=["agent"], dependencies=[Depends(get_current_user)])
settings = get_settings()


def _provider_error(exc: RuntimeError) -> HTTPException:
    detail = str(exc)
    code = 503 if "not_configured" in detail or "encryption_key" in detail else 502
    return HTTPException(status_code=code, detail=detail)


def _session_schema(session: AgentSession, message_count: int) -> AgentSessionRead:
    return AgentSessionRead(
        id=session.id,
        created_at=session.created_at,
        updated_at=session.updated_at,
        title=session.title,
        message_count=message_count,
    )


def _log_schema(log: AgentOperationLog) -> AgentOperationLogRead:
    return AgentOperationLogRead(
        id=log.id,
        created_at=log.created_at,
        session_id=log.session_id,
        turn_index=log.turn_index,
        operation_type=log.operation_type,
        user_message=log.user_message,
        description=log.description,
        tool_calls=log.tool_calls_json,
        change_summary=summarize_diff(log.before_state_json or {}, log.after_state_json or {}),
        is_undone=log.is_undone,
        undone_at=log.undone_at,
        linked_to_id=log.linked_to_id,
    )


@router.post("/chat", response_model=AgentTurnResult)
async def chat(payload: AgentChatRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await run_agent_turn(db, payload.messages, payload.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404 if str(exc).endswith("_not_found") else 400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _provider_error(exc) from exc


@router.post("/chat-with-files", response_model=AgentTurnResult)
async def chat_with_files(
    messages: str = Form(...),
    session_id: uuid.UUID | None = Form(default=None),
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="too_many_files")
    try:
        parsed_messages = TypeAdapter(list[ChatMessage]).validate_json(messages)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid_messages_json") from exc

    documents: list[UploadedDocument] = []
    total_bytes = 0
    for upload in files:
        content_type = (upload.content_type or "").lower()
        if content_type not in ALLOWED_AGENT_MIME_TYPES:
            raise HTTPException(status_code=400, detail="unsupported_agent_file_type")
        content = await upload.read()
        total_bytes += len(content)
        if total_bytes > settings.agent_max_file_bytes:
            raise HTTPException(status_code=400, detail="agent_files_too_large")
        documents.append(
            UploadedDocument(
                filename=upload.filename or f"upload-{uuid.uuid4()}",
                content_type=content_type,
                content=content,
            )
        )
    try:
        return await run_agent_turn(db, parsed_messages, session_id, documents)
    except ValueError as exc:
        raise HTTPException(status_code=404 if str(exc).endswith("_not_found") else 400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _provider_error(exc) from exc


def _pending_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    return HTTPException(
        status_code=404 if detail.endswith("_not_found") else 409,
        detail=detail,
    )


@router.post("/pending-actions/{action_id}/confirm", response_model=AgentTurnResult)
async def confirm_action(action_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await confirm_pending_action(db, action_id)
    except ValueError as exc:
        raise _pending_error(exc) from exc


@router.post("/pending-actions/{action_id}/cancel", response_model=AgentTurnResult)
async def cancel_action(action_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await cancel_pending_action(db, action_id)
    except ValueError as exc:
        raise _pending_error(exc) from exc


@router.get("/sessions", response_model=list[AgentSessionRead])
async def list_sessions(limit: int = Query(default=100, ge=1, le=500), db: AsyncSession = Depends(get_db)):
    return [_session_schema(session, count) for session, count in await agent_history_service.list_sessions(db, limit)]


@router.get("/sessions/{session_id}", response_model=AgentSessionDetail)
async def get_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await agent_history_service.get_session_detail(db, session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="agent_session_not_found")
    session, messages = result
    pending_rows = list(
        (
            await db.execute(
                select(AgentPendingAction).where(AgentPendingAction.session_id == session_id)
            )
        ).scalars()
    )
    pending_by_message = {
        row.assistant_message_id: row
        for row in pending_rows
        if row.assistant_message_id is not None
    }
    return AgentSessionDetail(
        **_session_schema(session, len(messages)).model_dump(),
        messages=[
            AgentMessageRead(
                id=message.id,
                created_at=message.created_at,
                role=message.role,
                content=message.content,
                attachments=message.attachments_json,
                tool_trace=message.tool_trace_json,
                pending_action=(
                    pending_action_schema(pending_by_message[message.id])
                    if message.id in pending_by_message
                    else None
                ),
            )
            for message in messages
        ],
    )


@router.get("/logs", response_model=AgentOperationLogPage)
async def list_logs(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await agent_history_service.list_operation_logs(db, offset, limit)
    return AgentOperationLogPage(
        items=[_log_schema(row) for row in rows], total=total, offset=offset, limit=limit
    )


@router.post("/logs/{log_id}/undo", response_model=UndoResult)
async def undo_log(log_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        log = await undo_service.undo_agent_operation(db, log_id)
    except ValueError as exc:
        raise HTTPException(status_code=404 if str(exc).endswith("_not_found") else 409, detail=str(exc)) from exc
    return UndoResult(ok=True, log_id=log.id, undone_at=log.undone_at)
