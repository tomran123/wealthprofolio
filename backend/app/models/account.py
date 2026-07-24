import uuid

from sqlalchemy import Enum as SAEnum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AccountType


class Account(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A specific account at an institution, owned by one family Owner."""

    __tablename__ = "accounts"

    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="RESTRICT"), nullable=False
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(
        SAEnum(AccountType, native_enum=False, length=20, values_callable=lambda x: [e.value for e in x]),
        default=AccountType.BROKERAGE,
        nullable=False,
    )
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    account_number_mask: Mapped[str | None] = mapped_column(String(50), nullable=True)

    institution: Mapped["Institution"] = relationship("Institution", back_populates="accounts")
    owner: Mapped["Owner"] = relationship("Owner", back_populates="accounts")
    holdings: Mapped[list["Holding"]] = relationship(
        "Holding", back_populates="account", cascade="all, delete-orphan"
    )
    transactions: Mapped[list["Transaction"]] = relationship("Transaction", back_populates="account")
