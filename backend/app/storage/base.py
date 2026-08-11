from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ObjectInfo:
    key: str
    size_bytes: int
    etag: str | None = None
    content_type: str | None = None


@dataclass(frozen=True, slots=True)
class PresignedUpload:
    url: str
    headers: dict[str, str]
    expires_at: datetime


class ObjectStorage(ABC):
    """Private object storage contract.

    Implementations may sign uploads, but reads always go through an
    authenticated API endpoint. No implementation returns a public read URL.
    """

    name: str

    @abstractmethod
    async def put_bytes(self, key: str, content: bytes, content_type: str) -> ObjectInfo:
        raise NotImplementedError

    @abstractmethod
    async def get_bytes(self, key: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    async def stat(self, key: str) -> ObjectInfo:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: str) -> None:
        raise NotImplementedError

    async def presign_upload(
        self,
        key: str,
        content_type: str,
        expires_seconds: int,
    ) -> PresignedUpload | None:
        return None
