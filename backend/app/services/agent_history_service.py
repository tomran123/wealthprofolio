import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.family_scope import family_scoped_get
from app.models import AgentMessage, AgentOperationLog, AgentSession


async def list_sessions(db: AsyncSession, limit: int = 100) -> list[tuple[AgentSession, int]]:
    message_counts = (
        select(AgentMessage.session_id, func.count(AgentMessage.id).label("message_count"))
        .group_by(AgentMessage.session_id)
        .subquery()
    )
    stmt = (
        select(AgentSession, func.coalesce(message_counts.c.message_count, 0))
        .outerjoin(message_counts, message_counts.c.session_id == AgentSession.id)
        .order_by(AgentSession.updated_at.desc())
        .limit(limit)
    )
    return [(session, int(count)) for session, count in (await db.execute(stmt)).all()]


async def get_session_detail(
    db: AsyncSession, session_id: uuid.UUID
) -> tuple[AgentSession, list[AgentMessage]] | None:
    session = await family_scoped_get(db, AgentSession, session_id)
    if session is None:
        return None
    stmt = (
        select(AgentMessage)
        .where(AgentMessage.session_id == session_id)
        .order_by(AgentMessage.created_at, AgentMessage.id)
    )
    messages = list((await db.execute(stmt)).scalars().all())
    return session, messages


async def list_operation_logs(
    db: AsyncSession, offset: int = 0, limit: int = 100
) -> tuple[list[AgentOperationLog], int]:
    total = int((await db.execute(select(func.count()).select_from(AgentOperationLog))).scalar_one())
    stmt = (
        select(AgentOperationLog)
        .order_by(AgentOperationLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all()), total
