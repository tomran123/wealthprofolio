import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    # Async ORM callers serialize rows immediately after commit=False flushes.
    # Fetch server-generated onupdate values in the UPDATE itself so attribute
    # access never attempts implicit async IO (which raises MissingGreenlet).
    __mapper_args__ = {"eager_defaults": True}

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FamilyScopedMixin:
    """Marker and common ownership column for every family-owned aggregate.

    Request sessions install a loader criterion for this mixin and validate
    writes before flush.  Keeping the marker on the mapped classes means a new
    family-owned model cannot silently omit query isolation.
    """

    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
