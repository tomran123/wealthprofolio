from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, FamilyScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import OwnerType

if TYPE_CHECKING:
    from app.models.account import Account


class Owner(UUIDPrimaryKeyMixin, TimestampMixin, FamilyScopedMixin, Base):
    """The real-world person or entity a piece of wealth belongs to (father, mother, etc.)."""

    __tablename__ = "owners"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_type: Mapped[OwnerType] = mapped_column(
        SAEnum(OwnerType, native_enum=False, length=30, values_callable=lambda x: [e.value for e in x]),
        default=OwnerType.INDIVIDUAL,
        nullable=False,
    )
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    accounts: Mapped[list["Account"]] = relationship("Account", back_populates="owner")
