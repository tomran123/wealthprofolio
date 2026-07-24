from sqlalchemy import Boolean, Enum as SAEnum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import LLMRole


class LLMProviderConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Encrypted configuration for one OpenAI-compatible chat or vision endpoint."""

    __tablename__ = "llm_provider_configs"

    name: Mapped[str] = mapped_column(String(60), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(30), nullable=False)
    role: Mapped[LLMRole] = mapped_column(
        SAEnum(LLMRole, native_enum=False, length=10, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
    )
    base_url: Mapped[str] = mapped_column(String(300), nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
