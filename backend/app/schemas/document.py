import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


DocumentStatus = Literal[
    "pending_upload",
    "uploading",
    "uploaded",
    "queued",
    "processing",
    "ready",
    "failed",
    "archived",
]
JobStatus = Literal["pending", "queued", "running", "succeeded", "failed", "cancelled"]


class DocumentUploadIntentCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(gt=0)
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    document_type: str | None = Field(default=None, max_length=60)
    owner_id: uuid.UUID | None = None
    institution_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    document_date: date | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("sha256")
    @classmethod
    def normalize_hash(cls, value: str | None) -> str | None:
        return value.lower() if value else None


class DocumentUploadTarget(BaseModel):
    method: Literal["PUT"] = "PUT"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    expires_at: datetime


class DocumentUploadIntent(BaseModel):
    document_id: uuid.UUID
    version_id: uuid.UUID
    status: DocumentStatus
    duplicate: bool
    upload: DocumentUploadTarget | None
    upload_token: str | None


class DocumentContentReceipt(BaseModel):
    document_id: uuid.UUID
    version_id: uuid.UUID
    received_bytes: int
    sha256: str


class DocumentCompleteRequest(BaseModel):
    upload_token: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")

    @field_validator("sha256")
    @classmethod
    def normalize_hash(cls, value: str | None) -> str | None:
        return value.lower() if value else None


class BackgroundJobRead(BaseModel):
    id: uuid.UUID
    job_type: str
    status: JobStatus
    stage: str | None
    progress: int
    message: str | None
    error: str | None
    result: dict[str, Any] | None
    resource_type: str | None
    resource_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class DocumentPageRead(BaseModel):
    id: uuid.UUID
    page_number: int
    status: Literal["pending", "processing", "ready", "failed"]
    text_preview: str | None
    ocr_confidence: float | None
    preview_url: str | None
    width: int | None
    height: int | None


class DocumentCitation(BaseModel):
    document_id: uuid.UUID
    filename: str
    page_number: int
    citation: str
    bounding_boxes: list[list[float]] = Field(default_factory=list)
    content: str | None = None


class DocumentExtractedField(BaseModel):
    name: str
    label: str | None = None
    value: Any = None
    confidence: float | None = None
    page_number: int | None = None
    citation: str | None = None
    bounding_box: list[float] | None = None


class DocumentExtractionRead(BaseModel):
    id: uuid.UUID
    extraction_type: str
    status: str
    summary: str | None
    confidence: float | None
    fields: list[DocumentExtractedField] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class DocumentSummary(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    document_type: str | None
    document_date: date | None
    status: DocumentStatus
    page_count: int
    owner_id: uuid.UUID | None
    institution_id: uuid.UUID | None
    account_id: uuid.UUID | None
    latest_job_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentSummary):
    sha256: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    pages: list[DocumentPageRead] = Field(default_factory=list)
    extractions: list[DocumentExtractionRead] = Field(default_factory=list)


class DocumentPageResult(BaseModel):
    items: list[DocumentSummary]
    total: int
    offset: int
    limit: int


class DocumentCompleteResult(BaseModel):
    document: DocumentSummary
    job: BackgroundJobRead


class DocumentReprocessResult(BaseModel):
    job: BackgroundJobRead


class KnowledgeFilters(BaseModel):
    limit: int = Field(default=10, ge=1, le=50)
    document_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    document_types: list[str] | None = Field(default=None, max_length=30)
    date_from: date | None = None
    date_to: date | None = None
    institution_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None


class KnowledgeSearchRequest(KnowledgeFilters):
    query: str = Field(min_length=1, max_length=1000)


class KnowledgeSearchItem(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page_number: int
    content: str
    score: float
    citation: str
    bounding_boxes: list[list[float]] = Field(default_factory=list)


class KnowledgeSearchResult(BaseModel):
    items: list[KnowledgeSearchItem]
    retrieval_mode: str
    degraded: bool


class KnowledgeQueryRequest(KnowledgeFilters):
    question: str = Field(min_length=1, max_length=3000)


class KnowledgeQueryResult(BaseModel):
    answer: str
    citations: list[DocumentCitation]
    retrieval_mode: str
    degraded: bool
    warnings: list[str] = Field(default_factory=list)


class DocumentTransactionDraftItem(BaseModel):
    id: str | None = None
    transaction_type: str
    account_id: uuid.UUID | None
    account_name: str | None = None
    instrument_id: uuid.UUID | None
    instrument_name: str | None
    instrument_symbol: str | None = None
    quantity: str | None
    price: str | None
    amount: str | None
    currency: str
    fee: str | None = None
    trade_date: date | None
    note: str | None = None
    confidence: float | None
    page_number: int | None
    citation: str | None


class DocumentTransactionDraft(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    extraction_id: uuid.UUID
    status: Literal["pending_review", "confirmed", "cancelled", "failed"]
    items: list[DocumentTransactionDraftItem]
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime
    resolved_at: datetime | None
