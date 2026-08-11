import asyncio
import hashlib
import os
import tempfile
from pathlib import Path, PurePosixPath

from app.storage.base import ObjectInfo, ObjectStorage


class LocalObjectStorage(ObjectStorage):
    """Filesystem-backed private storage for development and tests."""

    name = "local"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        relative = PurePosixPath(key)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("invalid_storage_key")
        path = self.root.joinpath(*relative.parts).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError("invalid_storage_key")
        return path

    def _put(self, key: str, content: bytes, content_type: str) -> ObjectInfo:
        path = self._path(key)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".upload-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return ObjectInfo(
            key=key,
            size_bytes=len(content),
            etag=hashlib.sha256(content).hexdigest(),
            content_type=content_type,
        )

    async def put_bytes(self, key: str, content: bytes, content_type: str) -> ObjectInfo:
        return await asyncio.to_thread(self._put, key, content, content_type)

    async def get_bytes(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise FileNotFoundError("storage_object_not_found") from exc

    async def stat(self, key: str) -> ObjectInfo:
        path = self._path(key)
        try:
            stat = await asyncio.to_thread(path.stat)
        except FileNotFoundError as exc:
            raise FileNotFoundError("storage_object_not_found") from exc
        return ObjectInfo(key=key, size_bytes=stat.st_size)

    async def delete(self, key: str) -> None:
        path = self._path(key)
        try:
            await asyncio.to_thread(path.unlink)
        except FileNotFoundError:
            return
