import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import UserDefinedType

from app.models.base import Base, FamilyScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

try:
    from pgvector.sqlalchemy import Vector as _PGVector
except ImportError:  # pragma: no cover - used only before optional dependency installation

    class _PGVector(UserDefinedType):
        """Import-safe pgvector type used by tooling before dependencies are installed."""

        cache_ok = True

        def __init__(self, dimensions: int) -> None:
            self.dimensions = dimensions

        def get_col_spec(self, **_: Any) -> str:
            return f"vector({self.dimensions})"


EMBEDDING_DIMENSIONS = 384


class Document(UUIDPrimaryKeyMixin, TimestampMixin, FamilyScopedMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index(
            "uq_documents_family_sha256_active",
            "family_id",
            "sha256",
            unique=True,
            postgresql_where=text(
                "sha256 IS NOT NULL AND status NOT IN ('failed', 'archived')"
            ),
        ),
        Index("ix_documents_family_status_created", "family_id", "status", "created_at"),
        Index("ix_documents_family_type_date", "family_id", "document_type", "document_date"),
    )

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    document_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending_upload")
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    storage_backend: Mapped[str] = mapped_column(String(30), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(900), nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("owners.id", ondelete="SET NULL"), nullable=True
    )
    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="SET NULL"), nullable=True
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    versions: Mapped[list["DocumentVersion"]] = relationship(
        "DocumentVersion", back_populates="document", cascade="all, delete-orphan"
    )
    pages: Mapped[list["DocumentPage"]] = relationship(
        "DocumentPage", back_populates="document", cascade="all, delete-orphan"
    )
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )
    extractions: Mapped[list["DocumentExtraction"]] = relationship(
        "DocumentExtraction", back_populates="document", cascade="all, delete-orphan"
    )


class DocumentVersion(UUIDPrimaryKeyMixin, TimestampMixin, FamilyScopedMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_document_version_number"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending_upload")
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expected_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actual_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_backend: Mapped[str] = mapped_column(String(30), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(900), nullable=False)
    upload_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    upload_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    document: Mapped[Document] = relationship("Document", back_populates="versions")


class DocumentPage(UUIDPrimaryKeyMixin, TimestampMixin, FamilyScopedMixin, Base):
    __tablename__ = "document_pages"
    __table_args__ = (
        UniqueConstraint("document_version_id", "page_number", name="uq_document_page_number"),
        Index("ix_document_pages_family_document_page", "family_id", "document_id", "page_number"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_provider: Mapped[str | None] = mapped_column(String(60), nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    bounding_boxes_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    preview_storage_key: Mapped[str | None] = mapped_column(String(900), nullable=True)
    preview_content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    document: Mapped[Document] = relationship("Document", back_populates="pages")


class DocumentChunk(UUIDPrimaryKeyMixin, TimestampMixin, FamilyScopedMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id", "chunk_index", name="uq_document_chunk_version_index"
        ),
        Index("ix_document_chunks_family_document", "family_id", "document_id"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    document_page_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_pages.id", ondelete="SET NULL"), nullable=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    bounding_boxes_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', coalesce(content, ''))", persisted=True),
        nullable=False,
    )
    embedding: Mapped[Any | None] = mapped_column(_PGVector(EMBEDDING_DIMENSIONS), nullable=True)

    document: Mapped[Document] = relationship("Document", back_populates="chunks")


class DocumentExtraction(UUIDPrimaryKeyMixin, TimestampMixin, FamilyScopedMixin, Base):
    __tablename__ = "document_extractions"
    __table_args__ = (
        Index(
            "ix_document_extractions_family_document_type",
            "family_id",
            "document_id",
            "extraction_type",
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    extraction_type: Mapped[str] = mapped_column(String(60), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ready")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider: Mapped[str] = mapped_column(String(60), nullable=False, default="local")
    data_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    citations_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped[Document] = relationship("Document", back_populates="extractions")


class DocumentLink(UUIDPrimaryKeyMixin, TimestampMixin, FamilyScopedMixin, Base):
    __tablename__ = "document_links"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "target_type",
            "target_id",
            "relation",
            name="uq_document_link_target_relation",
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    extraction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_extractions.id", ondelete="SET NULL"), nullable=True
    )
    target_type: Mapped[str] = mapped_column(String(60), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    relation: Mapped[str] = mapped_column(String(60), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class BackgroundJob(UUIDPrimaryKeyMixin, TimestampMixin, FamilyScopedMixin, Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        Index("ix_background_jobs_family_status_created", "family_id", "status", "created_at"),
        Index("ix_background_jobs_family_resource", "family_id", "resource_type", "resource_id"),
    )

    job_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    stage: Mapped[str | None] = mapped_column(String(60), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str | None] = mapped_column(String(300), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
