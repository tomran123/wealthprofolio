import asyncio
import uuid
from contextlib import suppress

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.context import COOKIE_NAME
from app.api.deps import get_db, get_request_context
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.core.family_scope import RequestContext, bind_request_context
from app.core.security import decode_access_token
from app.models import FamilyMembership, User
from app.schemas.document import BackgroundJobRead
from app.services.document_service import get_job, job_schema
from app.services.job_event_service import job_channel

router = APIRouter(tags=["jobs"])
settings = get_settings()
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}


@router.get(
    "/api/v1/jobs/{job_id}",
    response_model=BackgroundJobRead,
    dependencies=[Depends(get_request_context)],
)
async def read_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    job = await get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="background_job_not_found")
    return job_schema(job)


async def _websocket_context(
    websocket: WebSocket,
    db: AsyncSession,
) -> RequestContext | None:
    token = websocket.cookies.get(COOKIE_NAME)
    claims = decode_access_token(token) if token else None
    if claims is None:
        return None
    requested_family = websocket.headers.get("x-family-id")
    try:
        family_id = uuid.UUID(requested_family) if requested_family else claims.active_family_id
    except ValueError:
        return None
    user = await db.get(User, claims.user_id)
    if user is None:
        return None
    membership = (
        await db.execute(
            select(FamilyMembership)
            .where(
                FamilyMembership.user_id == user.id,
                FamilyMembership.family_id == family_id,
                FamilyMembership.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        return None
    context = RequestContext(
        user_id=user.id,
        family_id=membership.family_id,
        role=membership.role,
        token_jti=claims.jti,
    )
    bind_request_context(db, context)
    return context


@router.websocket("/api/v1/ws/jobs/{job_id}")
async def job_updates(websocket: WebSocket, job_id: uuid.UUID):
    origin = websocket.headers.get("origin")
    if origin and origin not in settings.cors_origins:
        await websocket.close(code=4403, reason="origin_rejected")
        return
    async with AsyncSessionLocal() as db:
        context = await _websocket_context(websocket, db)
        if context is None:
            await websocket.close(code=4401, reason="not_authenticated")
            return
        job = await get_job(db, job_id)
        if job is None:
            await websocket.close(code=4404, reason="background_job_not_found")
            return
        await websocket.accept()
        last_snapshot: tuple | None = None
        pubsub = None
        redis_client = None
        if settings.redis_url:
            try:
                from redis.asyncio import Redis

                redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
                pubsub = redis_client.pubsub()
                await pubsub.subscribe(job_channel(context.family_id, job_id))
            except Exception:
                if pubsub is not None:
                    with suppress(Exception):
                        await pubsub.aclose()
                if redis_client is not None:
                    with suppress(Exception):
                        await redis_client.aclose()
                pubsub = None
                redis_client = None
        try:
            while True:
                db.expire_all()
                job = await get_job(db, job_id)
                if job is None:
                    await websocket.close(code=4404, reason="background_job_not_found")
                    return
                snapshot_key = (
                    job.status,
                    job.stage,
                    job.progress,
                    job.updated_at,
                    job.error,
                )
                if snapshot_key != last_snapshot:
                    await websocket.send_json(
                        {
                            "type": "job.snapshot",
                            "job": job_schema(job).model_dump(mode="json"),
                        }
                    )
                    last_snapshot = snapshot_key
                if job.status in TERMINAL_JOB_STATUSES:
                    await websocket.close(code=1000, reason="job complete")
                    return
                if pubsub is not None:
                    try:
                        await pubsub.get_message(
                            ignore_subscribe_messages=True,
                            timeout=0.75,
                        )
                    except Exception:
                        with suppress(Exception):
                            await pubsub.aclose()
                        pubsub = None
                else:
                    await asyncio.sleep(0.75)
        except (WebSocketDisconnect, RuntimeError):
            return
        finally:
            if pubsub is not None:
                with suppress(Exception):
                    await pubsub.unsubscribe(job_channel(context.family_id, job_id))
                with suppress(Exception):
                    await pubsub.aclose()
            if redis_client is not None:
                with suppress(Exception):
                    await redis_client.aclose()
