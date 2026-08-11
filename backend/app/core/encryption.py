"""Versioned AES-256-GCM envelope encryption.

Production can ask Alibaba Cloud KMS to generate and wrap a one-time data key.
Local development uses an AES-GCM wrapping key derived from the existing
application encryption secret.  The stored envelope never contains a plaintext
data key and is self-describing for future key rotation.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from dataclasses import dataclass
from typing import Protocol

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import get_settings

ENVELOPE_PREFIX = "wpsec:v1:"
_APP_CONTEXT = "wealthportfolio"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True, slots=True)
class WrappedDataKey:
    plaintext: bytes
    ciphertext: str
    key_id: str
    provider: str


class DataKeyProvider(Protocol):
    async def generate(self, purpose: str) -> WrappedDataKey: ...

    async def unwrap(self, wrapped: str, purpose: str) -> bytes: ...


def _local_master_key() -> bytes:
    settings = get_settings()
    configured = getattr(settings, "app_encryption_key", None) or settings.llm_encryption_key
    if not configured:
        raise RuntimeError("app_encryption_key_not_configured")
    try:
        root = _unb64(configured)
    except (ValueError, TypeError):
        root = configured.encode("utf-8")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"wealthportfolio/local-envelope-wrap/v1",
    ).derive(root)


class LocalDataKeyProvider:
    provider = "local-aesgcm"
    key_id = "local-derived-v1"

    async def generate(self, purpose: str) -> WrappedDataKey:
        data_key = os.urandom(32)
        nonce = os.urandom(12)
        aad = f"{_APP_CONTEXT}:{purpose}:key-wrap:v1".encode()
        ciphertext = AESGCM(_local_master_key()).encrypt(nonce, data_key, aad)
        return WrappedDataKey(
            plaintext=data_key,
            ciphertext=_b64(nonce + ciphertext),
            key_id=self.key_id,
            provider=self.provider,
        )

    async def unwrap(self, wrapped: str, purpose: str) -> bytes:
        payload = _unb64(wrapped)
        if len(payload) < 29:
            raise RuntimeError("encrypted_data_key_invalid")
        aad = f"{_APP_CONTEXT}:{purpose}:key-wrap:v1".encode()
        try:
            return AESGCM(_local_master_key()).decrypt(
                payload[:12],
                payload[12:],
                aad,
            )
        except Exception as exc:
            raise RuntimeError("encrypted_data_key_decryption_failed") from exc


class AlibabaKMSDataKeyProvider:
    provider = "alibaba-kms"

    def __init__(self) -> None:
        settings = get_settings()
        self.key_id = str(getattr(settings, "alicloud_kms_key_id", "") or "")
        self.region_id = str(getattr(settings, "alicloud_region_id", "") or "")
        self.endpoint = str(getattr(settings, "alicloud_kms_endpoint", "") or "")
        if not self.key_id or not self.region_id:
            raise RuntimeError("alicloud_kms_configuration_required")

    @staticmethod
    def _context(purpose: str) -> dict[str, str]:
        return {"application": _APP_CONTEXT, "purpose": purpose}

    def _client(self):
        try:
            from alibabacloud_credentials.client import Client as CredentialClient
            from alibabacloud_kms20160120.client import Client as KMSClient
            from alibabacloud_tea_openapi.models import Config
        except ImportError as exc:
            raise RuntimeError("alicloud_kms_sdk_not_installed") from exc
        config = Config(
            credential=CredentialClient(),
            region_id=self.region_id,
            endpoint=self.endpoint or f"kms-vpc.{self.region_id}.aliyuncs.com",
        )
        return KMSClient(config)

    def _generate_sync(self, purpose: str) -> WrappedDataKey:
        from alibabacloud_kms20160120.models import GenerateDataKeyRequest

        response = self._client().generate_data_key(
            GenerateDataKeyRequest(
                key_id=self.key_id,
                number_of_bytes=32,
                encryption_context=self._context(purpose),
            )
        )
        body = response.body
        if not body or not body.plaintext or not body.ciphertext_blob:
            raise RuntimeError("alicloud_kms_generate_data_key_failed")
        plaintext = base64.b64decode(body.plaintext, validate=True)
        if len(plaintext) != 32:
            raise RuntimeError("alicloud_kms_data_key_invalid")
        return WrappedDataKey(
            plaintext=plaintext,
            ciphertext=body.ciphertext_blob,
            key_id=body.key_id or self.key_id,
            provider=self.provider,
        )

    def _unwrap_sync(self, wrapped: str, purpose: str) -> bytes:
        from alibabacloud_kms20160120.models import DecryptRequest

        response = self._client().decrypt(
            DecryptRequest(
                ciphertext_blob=wrapped,
                encryption_context=self._context(purpose),
            )
        )
        body = response.body
        if not body or not body.plaintext:
            raise RuntimeError("alicloud_kms_decrypt_data_key_failed")
        plaintext = base64.b64decode(body.plaintext, validate=True)
        if len(plaintext) != 32:
            raise RuntimeError("alicloud_kms_data_key_invalid")
        return plaintext

    async def generate(self, purpose: str) -> WrappedDataKey:
        return await asyncio.to_thread(self._generate_sync, purpose)

    async def unwrap(self, wrapped: str, purpose: str) -> bytes:
        return await asyncio.to_thread(self._unwrap_sync, wrapped, purpose)


def _provider(name: str | None = None) -> DataKeyProvider:
    selected = (
        name
        or str(getattr(get_settings(), "encryption_provider", "local") or "local")
    ).lower()
    if selected in {"alicloud", "alibaba-kms", "kms"}:
        return AlibabaKMSDataKeyProvider()
    if selected in {"local", "local-aesgcm"}:
        return LocalDataKeyProvider()
    raise RuntimeError("unsupported_encryption_provider")


async def encrypt_secret(plaintext: str, *, purpose: str) -> str:
    provider = _provider()
    wrapped = await provider.generate(purpose)
    nonce = os.urandom(12)
    aad = f"{_APP_CONTEXT}:{purpose}:payload:v1".encode()
    ciphertext = AESGCM(wrapped.plaintext).encrypt(
        nonce,
        plaintext.encode("utf-8"),
        aad,
    )
    payload = {
        "algorithm": "AES-256-GCM",
        "ciphertext": _b64(ciphertext),
        "data_key": wrapped.ciphertext,
        "key_id": wrapped.key_id,
        "nonce": _b64(nonce),
        "provider": wrapped.provider,
        "purpose": purpose,
        "version": 1,
    }
    encoded = _b64(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return ENVELOPE_PREFIX + encoded


async def decrypt_secret(envelope: str, *, purpose: str) -> str:
    if not envelope.startswith(ENVELOPE_PREFIX):
        raise RuntimeError("unsupported_secret_envelope")
    try:
        payload = json.loads(
            _unb64(envelope.removeprefix(ENVELOPE_PREFIX)).decode("utf-8")
        )
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("secret_envelope_invalid") from exc
    if (
        payload.get("version") != 1
        or payload.get("algorithm") != "AES-256-GCM"
        or payload.get("purpose") != purpose
    ):
        raise RuntimeError("secret_envelope_invalid")
    data_key = await _provider(str(payload.get("provider"))).unwrap(
        str(payload["data_key"]),
        purpose,
    )
    aad = f"{_APP_CONTEXT}:{purpose}:payload:v1".encode()
    try:
        plaintext = AESGCM(data_key).decrypt(
            _unb64(str(payload["nonce"])),
            _unb64(str(payload["ciphertext"])),
            aad,
        )
        return plaintext.decode("utf-8")
    except Exception as exc:
        raise RuntimeError("secret_decryption_failed") from exc
