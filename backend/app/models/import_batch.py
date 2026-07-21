from sqlalchemy import Enum as SAEnum, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ImportBatchStatus


class ImportBatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A CSV/Excel upload: parsed rows + match results are cached here so the user can
    preview the outcome before committing it to the database."""

    __tablename__ = "import_batches"

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ImportBatchStatus] = mapped_column(
        SAEnum(ImportBatchStatus, native_enum=False, length=20, values_callable=lambda x: [e.value for e in x]),
        default=ImportBatchStatus.PENDING,
        nullable=False,
    )
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    matched_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    parsed_rows: Mapped[dict] = mapped_column(JSONB, nullable=False)
