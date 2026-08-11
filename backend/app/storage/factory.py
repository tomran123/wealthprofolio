from functools import lru_cache

from app.core.config import get_settings
from app.storage.base import ObjectStorage
from app.storage.local import LocalObjectStorage
from app.storage.oss import AlibabaOSSObjectStorage
from app.storage.s3 import S3CompatibleObjectStorage


@lru_cache(maxsize=4)
def _storage_for_backend(backend: str) -> ObjectStorage:
    settings = get_settings()
    if backend == "local":
        return LocalObjectStorage(settings.document_storage_local_path)
    if backend == "minio":
        return S3CompatibleObjectStorage(
            endpoint_url=settings.document_storage_endpoint,
            bucket=settings.document_storage_bucket,
            access_key=settings.document_storage_access_key,
            secret_key=settings.document_storage_secret_key,
            region=settings.document_storage_region,
            secure=settings.document_storage_secure,
            public_endpoint_url=settings.document_storage_public_endpoint,
        )
    if backend == "oss":
        if (
            settings.environment in {"production", "prod"}
            and not settings.document_storage_public_endpoint
        ):
            raise RuntimeError("document_storage_public_endpoint_required")
        return AlibabaOSSObjectStorage(
            endpoint=settings.document_storage_endpoint,
            bucket=settings.document_storage_bucket,
            access_key_id=settings.document_storage_access_key,
            access_key_secret=settings.document_storage_secret_key,
            kms_key_id=settings.document_storage_kms_key_id,
            public_endpoint=settings.document_storage_public_endpoint,
            secure=settings.document_storage_secure,
        )
    raise RuntimeError("unsupported_document_storage_backend")


def get_object_storage(backend: str | None = None) -> ObjectStorage:
    settings = get_settings()
    return _storage_for_backend((backend or settings.document_storage_backend).lower())
