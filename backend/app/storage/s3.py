import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from app.storage.base import ObjectInfo, ObjectStorage, PresignedUpload


class S3CompatibleObjectStorage(ObjectStorage):
    """Private S3-compatible adapter used by MinIO and portable deployments."""

    name = "minio"

    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str | None = None,
        secure: bool = False,
        public_endpoint_url: str | None = None,
    ) -> None:
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover - dependency is deployment-specific
            raise RuntimeError("boto3_not_installed") from exc
        self.bucket = bucket
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region or "us-east-1",
            use_ssl=secure,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        self._presign_client: Any = (
            boto3.client(
                "s3",
                endpoint_url=public_endpoint_url,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region or "us-east-1",
                use_ssl=public_endpoint_url.startswith("https://"),
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )
            if public_endpoint_url
            else self._client
        )

    async def put_bytes(self, key: str, content: bytes, content_type: str) -> ObjectInfo:
        response = await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
        )
        return ObjectInfo(
            key=key,
            size_bytes=len(content),
            etag=str(response.get("ETag") or "").strip('"') or None,
            content_type=content_type,
        )

    async def get_bytes(self, key: str) -> bytes:
        response = await asyncio.to_thread(self._client.get_object, Bucket=self.bucket, Key=key)
        return await asyncio.to_thread(response["Body"].read)

    async def stat(self, key: str) -> ObjectInfo:
        response = await asyncio.to_thread(self._client.head_object, Bucket=self.bucket, Key=key)
        return ObjectInfo(
            key=key,
            size_bytes=int(response["ContentLength"]),
            etag=str(response.get("ETag") or "").strip('"') or None,
            content_type=response.get("ContentType"),
        )

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self.bucket, Key=key)

    async def presign_upload(
        self,
        key: str,
        content_type: str,
        expires_seconds: int,
    ) -> PresignedUpload:
        params = {"Bucket": self.bucket, "Key": key, "ContentType": content_type}
        url = await asyncio.to_thread(
            self._presign_client.generate_presigned_url,
            "put_object",
            Params=params,
            ExpiresIn=expires_seconds,
            HttpMethod="PUT",
        )
        return PresignedUpload(
            url=url,
            headers={"Content-Type": content_type},
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_seconds),
        )
