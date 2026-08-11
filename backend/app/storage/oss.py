import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from app.storage.base import ObjectInfo, ObjectStorage, PresignedUpload


class AlibabaOSSObjectStorage(ObjectStorage):
    """Alibaba Cloud OSS adapter with private objects and optional SSE-KMS."""

    name = "oss"

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key_id: str,
        access_key_secret: str,
        kms_key_id: str | None = None,
        public_endpoint: str | None = None,
        secure: bool = True,
    ) -> None:
        try:
            import oss2
        except ImportError as exc:  # pragma: no cover - dependency is deployment-specific
            raise RuntimeError("oss2_not_installed") from exc
        self._oss2: Any = oss2
        def normalized_endpoint(value: str) -> str:
            if secure and value.lower().startswith("http://"):
                raise RuntimeError("insecure_oss_endpoint_forbidden")
            if "://" in value:
                return value
            return f"{'https' if secure else 'http'}://{value}"

        auth = oss2.Auth(access_key_id, access_key_secret)
        self.bucket = oss2.Bucket(
            auth,
            normalized_endpoint(endpoint),
            bucket,
            connect_timeout=15,
        )
        self._presign_bucket = (
            oss2.Bucket(
                auth,
                normalized_endpoint(public_endpoint),
                bucket,
                connect_timeout=15,
            )
            if public_endpoint
            else self.bucket
        )
        self.kms_key_id = kms_key_id

    def _headers(self, content_type: str) -> dict[str, str]:
        headers = {"Content-Type": content_type}
        if self.kms_key_id:
            headers.update(
                {
                    "x-oss-server-side-encryption": "KMS",
                    "x-oss-server-side-encryption-key-id": self.kms_key_id,
                }
            )
        else:
            headers["x-oss-server-side-encryption"] = "AES256"
        return headers

    async def put_bytes(self, key: str, content: bytes, content_type: str) -> ObjectInfo:
        result = await asyncio.to_thread(
            self.bucket.put_object,
            key,
            content,
            headers=self._headers(content_type),
        )
        return ObjectInfo(
            key=key,
            size_bytes=len(content),
            etag=getattr(result, "etag", None),
            content_type=content_type,
        )

    async def get_bytes(self, key: str) -> bytes:
        result = await asyncio.to_thread(self.bucket.get_object, key)
        return await asyncio.to_thread(result.read)

    async def stat(self, key: str) -> ObjectInfo:
        result = await asyncio.to_thread(self.bucket.head_object, key)
        return ObjectInfo(
            key=key,
            size_bytes=int(result.content_length),
            etag=getattr(result, "etag", None),
            content_type=getattr(result, "content_type", None),
        )

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.bucket.delete_object, key)

    async def presign_upload(
        self,
        key: str,
        content_type: str,
        expires_seconds: int,
    ) -> PresignedUpload:
        headers = self._headers(content_type)
        url = await asyncio.to_thread(
            self._presign_bucket.sign_url,
            "PUT",
            key,
            expires_seconds,
            headers=headers,
            slash_safe=True,
        )
        return PresignedUpload(
            url=url,
            headers=headers,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_seconds),
        )
