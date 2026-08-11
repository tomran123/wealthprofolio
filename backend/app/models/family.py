import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class Family(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "families"
    __table_args__ = (UniqueConstraint("slug", name="uq_families_slug"),)

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, index=True)

    memberships: Mapped[list["FamilyMembership"]] = relationship(
        "FamilyMembership",
        back_populates="family",
        cascade="all, delete-orphan",
    )


class FamilyMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "family_memberships"
    __table_args__ = (
        UniqueConstraint("family_id", "user_id", name="uq_family_membership_family_user"),
    )

    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    family: Mapped[Family] = relationship("Family", back_populates="memberships")
    user: Mapped["User"] = relationship("User", back_populates="family_memberships")
