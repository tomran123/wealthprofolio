import uuid
from dataclasses import dataclass

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria
from sqlalchemy.sql import visitors
from sqlalchemy.sql.schema import Table

from app.models.base import Base, FamilyScopedMixin

FAMILY_ID_INFO_KEY = "family_id"
REQUEST_CONTEXT_INFO_KEY = "request_context"
FAMILY_SCOPE_BYPASS_INFO_KEY = "family_scope_bypass"
EXPLICIT_FAMILY_SCOPE_OPTION = "explicit_family_scope"


@dataclass(frozen=True, slots=True)
class RequestContext:
    user_id: uuid.UUID
    family_id: uuid.UUID
    role: str
    token_jti: uuid.UUID


def bind_request_context(db: AsyncSession, context: RequestContext) -> None:
    db.info[FAMILY_ID_INFO_KEY] = context.family_id
    db.info[REQUEST_CONTEXT_INFO_KEY] = context


def get_bound_request_context(db: AsyncSession) -> RequestContext | None:
    value = db.info.get(REQUEST_CONTEXT_INFO_KEY)
    return value if isinstance(value, RequestContext) else None


def require_bound_family_id(db: AsyncSession) -> uuid.UUID:
    family_id = db.info.get(FAMILY_ID_INFO_KEY)
    if not isinstance(family_id, uuid.UUID):
        raise RuntimeError("family_context_required")
    return family_id


def explicitly_family_scoped(db: AsyncSession, statement):
    """Authorize a reviewed Core statement that contains its own family clause.

    ORM statements should rely on the global loader criterion. A few backup
    operations intentionally use SQLAlchemy Core tables; those statements must
    bind a request family first and opt in one by one so a new unscoped Core
    query fails closed.
    """

    require_bound_family_id(db)
    return statement.execution_options(**{EXPLICIT_FAMILY_SCOPE_OPTION: True})


async def family_scoped_get(db: AsyncSession, model, object_id):
    """Identity-map-safe lookup for a family-owned object.

    Session.get() can return an object loaded before a context was bound without
    issuing SQL. Public ID lookups use this helper so family ownership is always
    part of the executed statement.
    """

    family_id = require_bound_family_id(db)
    statement = select(model).where(
        model.id == object_id,
        model.family_id == family_id,
    )
    return (await db.execute(statement)).scalar_one_or_none()


def _family_table_keys() -> set[tuple[str | None, str]]:
    return {
        (mapper.local_table.schema, mapper.local_table.name)
        for mapper in Base.registry.mappers
        if issubclass(mapper.class_, FamilyScopedMixin)
    }


def _statement_family_shape(statement) -> tuple[bool, bool]:
    """Return (contains_family_table, contains_annotated_family_mapper)."""

    table_keys = _family_table_keys()
    contains_family_table = False
    contains_annotated_mapper = False
    for node in visitors.iterate(statement):
        annotations = getattr(node, "_annotations", {})
        parent_mapper = annotations.get("parentmapper")
        if parent_mapper is not None and issubclass(
            parent_mapper.class_, FamilyScopedMixin
        ):
            contains_annotated_mapper = True
            contains_family_table = True
        if isinstance(node, Table) and (node.schema, node.name) in table_keys:
            contains_family_table = True
    return contains_family_table, contains_annotated_mapper


@event.listens_for(Session, "do_orm_execute")
def _apply_family_loader_criteria(execute_state: ORMExecuteState) -> None:
    if not (
        execute_state.is_select
        or execute_state.is_update
        or execute_state.is_delete
    ):
        return
    family_mappers = {
        mapper
        for mapper in getattr(execute_state, "all_mappers", ())
        if issubclass(mapper.class_, FamilyScopedMixin)
    }
    contains_family_table, contains_annotated_mapper = _statement_family_shape(
        execute_state.statement
    )
    if not family_mappers and not contains_family_table:
        return
    bypass_requested = bool(
        execute_state.execution_options.get("include_all_families")
    )
    bypass_authorized = (
        execute_state.session.info.get(FAMILY_SCOPE_BYPASS_INFO_KEY) is True
    )
    if bypass_requested:
        if not bypass_authorized:
            raise RuntimeError("family_scope_bypass_not_authorized")
        return
    family_id = execute_state.session.info.get(FAMILY_ID_INFO_KEY)
    if not isinstance(family_id, uuid.UUID):
        raise RuntimeError("family_context_required")
    if execute_state.execution_options.get(EXPLICIT_FAMILY_SCOPE_OPTION):
        return
    if not family_mappers and not contains_annotated_mapper:
        raise RuntimeError("explicit_family_scope_required_for_core_statement")
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            FamilyScopedMixin,
            lambda model: model.family_id == family_id,
            include_aliases=True,
        )
    )


@event.listens_for(Session, "before_flush")
def _enforce_family_owned_writes(
    session: Session,
    flush_context: object,
    instances: object,
) -> None:
    family_id = session.info.get(FAMILY_ID_INFO_KEY)
    family_owned = [
        obj
        for obj in session.new.union(session.dirty).union(session.deleted)
        if isinstance(obj, FamilyScopedMixin)
    ]
    if not family_owned:
        return
    if not isinstance(family_id, uuid.UUID):
        if session.info.get(FAMILY_SCOPE_BYPASS_INFO_KEY) is True:
            return
        raise RuntimeError("family_context_required")
    for obj in session.new:
        if not isinstance(obj, FamilyScopedMixin):
            continue
        current = getattr(obj, "family_id", None)
        if current is None:
            setattr(obj, "family_id", family_id)
        elif current != family_id:
            raise ValueError("cross_family_write_forbidden")
    for obj in session.dirty.union(session.deleted):
        if isinstance(obj, FamilyScopedMixin) and getattr(obj, "family_id", None) != family_id:
            raise ValueError("cross_family_write_forbidden")
