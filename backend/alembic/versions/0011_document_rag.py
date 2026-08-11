"""add private document center, RAG index, and durable background jobs

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-28
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


class Vector384(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kwargs) -> str:
        return "vector(384)"


def _id() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True)


def _family() -> sa.Column:
    return sa.Column(
        "family_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("families.id", ondelete="RESTRICT"),
        nullable=False,
    )


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def upgrade() -> None:
    # pgvector remains an OLTP-side index. Managed PostgreSQL deployments must
    # allow the vector extension before this revision is applied.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "documents",
        _id(),
        *_timestamps(),
        _family(),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("document_type", sa.String(length=60), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending_upload"),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("storage_backend", sa.String(length=30), nullable=False),
        sa.Column("storage_key", sa.String(length=900), nullable=False),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("owners.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "institution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("institutions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_documents_family_id", "documents", ["family_id"])
    op.create_index(
        "uq_documents_family_sha256_active",
        "documents",
        ["family_id", "sha256"],
        unique=True,
        postgresql_where=sa.text(
            "sha256 IS NOT NULL AND status NOT IN ('failed', 'archived')"
        ),
    )
    op.create_index(
        "ix_documents_family_status_created",
        "documents",
        ["family_id", "status", "created_at"],
    )
    op.create_index(
        "ix_documents_family_type_date",
        "documents",
        ["family_id", "document_type", "document_date"],
    )

    op.create_table(
        "document_versions",
        _id(),
        *_timestamps(),
        _family(),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending_upload"),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("expected_sha256", sa.String(length=64), nullable=True),
        sa.Column("actual_sha256", sa.String(length=64), nullable=True),
        sa.Column("storage_backend", sa.String(length=30), nullable=False),
        sa.Column("storage_key", sa.String(length=900), nullable=False),
        sa.Column("upload_token_hash", sa.String(length=64), nullable=True),
        sa.Column("upload_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint("document_id", "version_number", name="uq_document_version_number"),
    )
    op.create_index("ix_document_versions_family_id", "document_versions", ["family_id"])
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])

    op.create_table(
        "document_pages",
        _id(),
        *_timestamps(),
        _family(),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("ocr_provider", sa.String(length=60), nullable=True),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column(
            "bounding_boxes_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("preview_storage_key", sa.String(length=900), nullable=True),
        sa.Column("preview_content_type", sa.String(length=100), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.UniqueConstraint("document_version_id", "page_number", name="uq_document_page_number"),
    )
    op.create_index("ix_document_pages_family_id", "document_pages", ["family_id"])
    op.create_index(
        "ix_document_pages_family_document_page",
        "document_pages",
        ["family_id", "document_id", "page_number"],
    )

    op.create_table(
        "document_chunks",
        _id(),
        *_timestamps(),
        _family(),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_page_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_pages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "bounding_boxes_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', coalesce(content, ''))", persisted=True),
            nullable=False,
        ),
        sa.Column("embedding", Vector384(), nullable=True),
        sa.UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name="uq_document_chunk_version_index",
        ),
    )
    op.create_index("ix_document_chunks_family_id", "document_chunks", ["family_id"])
    op.create_index(
        "ix_document_chunks_family_document",
        "document_chunks",
        ["family_id", "document_id"],
    )
    op.create_index(
        "ix_document_chunks_search_vector",
        "document_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.execute(
        """
        CREATE INDEX ix_document_chunks_embedding_hnsw
        ON document_chunks USING hnsw (embedding vector_cosine_ops)
        WHERE embedding IS NOT NULL
        """
    )

    op.create_table(
        "document_extractions",
        _id(),
        *_timestamps(),
        _family(),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("extraction_type", sa.String(length=60), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="ready"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("provider", sa.String(length=60), nullable=False, server_default="local"),
        sa.Column(
            "data_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "citations_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_document_extractions_family_id", "document_extractions", ["family_id"])
    op.create_index(
        "ix_document_extractions_family_document_type",
        "document_extractions",
        ["family_id", "document_id", "extraction_type"],
    )

    op.create_table(
        "document_links",
        _id(),
        *_timestamps(),
        _family(),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "extraction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_extractions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("target_type", sa.String(length=60), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation", sa.String(length=60), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint(
            "document_id",
            "target_type",
            "target_id",
            "relation",
            name="uq_document_link_target_relation",
        ),
    )
    op.create_index("ix_document_links_family_id", "document_links", ["family_id"])
    op.create_index("ix_document_links_document_id", "document_links", ["document_id"])

    op.create_table(
        "background_jobs",
        _id(),
        *_timestamps(),
        _family(),
        sa.Column("job_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(length=60), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.String(length=300), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "input_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("result_json", postgresql.JSONB(), nullable=True),
        sa.Column("resource_type", sa.String(length=60), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_background_jobs_family_id", "background_jobs", ["family_id"])
    op.create_index("ix_background_jobs_job_type", "background_jobs", ["job_type"])
    op.create_index(
        "ix_background_jobs_family_status_created",
        "background_jobs",
        ["family_id", "status", "created_at"],
    )
    op.create_index(
        "ix_background_jobs_family_resource",
        "background_jobs",
        ["family_id", "resource_type", "resource_id"],
    )


def downgrade() -> None:
    op.drop_table("background_jobs")
    op.drop_table("document_links")
    op.drop_table("document_extractions")
    op.drop_index("ix_document_chunks_embedding_hnsw", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_table("document_pages")
    op.drop_table("document_versions")
    op.drop_table("documents")
    # Extensions are cluster-scoped and may be used by other schemas/apps.
    # Leaving pgvector installed makes this downgrade non-destructive.
