from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.family import FamilyMembership


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An application login account. MVP uses a single shared admin account, but this is
    a proper table so multi-user support can be added later without a schema migration."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username", name="uq_users_username"),)

    username: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_system_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    family_memberships: Mapped[list["FamilyMembership"]] = relationship(
        "FamilyMembership",
        back_populates="user",
        cascade="all, delete-orphan",
    )
