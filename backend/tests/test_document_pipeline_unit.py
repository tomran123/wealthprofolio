import math
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

import fitz

from app.providers.ocr.alibaba_ocr import AlibabaCloudOCRProvider
from app.providers.ocr.base import OCRProvider
from app.providers.ocr.registry import get_ocr_provider
from app.providers.ocr.tencent_scf import TencentSCFOCRProvider
from app.services.document_ingestion import (
    local_hash_embedding,
    local_structured_extraction,
    split_text,
)
from app.services.document_security_service import (
    inspect_document_content,
    safe_filename,
    validate_upload_metadata,
)
from app.storage.local import LocalObjectStorage
from app.storage.oss import AlibabaOSSObjectStorage
from app.storage.s3 import S3CompatibleObjectStorage


def sample_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "2026-07-24 BUY AAPL 10 @ 200 USD 2000")
    content = document.tobytes()
    document.close()
    return content


class DocumentSecurityTests(unittest.IsolatedAsyncioTestCase):
    def test_upload_metadata_rejects_extension_mismatch(self):
        with self.assertRaisesRegex(ValueError, "document_extension_mime_mismatch"):
            validate_upload_metadata("statement.png", "application/pdf", 100, None)

    def test_filename_is_reduced_to_safe_leaf(self):
        self.assertEqual(safe_filename("../../private/statement.pdf"), "statement.pdf")

    async def test_pdf_magic_hash_and_page_inspection(self):
        content = sample_pdf()
        result = await inspect_document_content(
            content,
            "application/pdf",
            expected_size=len(content),
        )
        self.assertEqual(result.page_count, 1)
        self.assertEqual(len(result.sha256), 64)
        self.assertIn("virus_scan_not_configured", result.warnings)

    async def test_declared_mime_must_match_magic(self):
        with self.assertRaisesRegex(ValueError, "document_magic_mime_mismatch"):
            await inspect_document_content(sample_pdf(), "image/png")


class LocalStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_local_round_trip_and_traversal_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalObjectStorage(directory)
            info = await storage.put_bytes("family/doc/source", b"secret", "application/pdf")
            self.assertEqual(info.size_bytes, 6)
            self.assertEqual(await storage.get_bytes("family/doc/source"), b"secret")
            mode = Path(directory, "family/doc/source").stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)
            with self.assertRaisesRegex(ValueError, "invalid_storage_key"):
                await storage.put_bytes("../escape", b"x", "text/plain")


class PresignedEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_minio_presign_uses_browser_reachable_endpoint(self):
        storage = S3CompatibleObjectStorage(
            endpoint_url="http://minio.internal:9000",
            public_endpoint_url="https://objects.example.com",
            bucket="private",
            access_key="test-access",
            secret_key="test-secret",
        )
        target = await storage.presign_upload("family/document/source", "application/pdf", 60)
        self.assertEqual(urlsplit(target.url).netloc, "objects.example.com")

    async def test_oss_presign_uses_browser_reachable_endpoint(self):
        storage = AlibabaOSSObjectStorage(
            endpoint="oss-internal.example.com",
            public_endpoint="oss-public.example.com",
            bucket="private",
            access_key_id="test-access",
            access_key_secret="test-secret",
            secure=True,
        )
        target = await storage.presign_upload("family/document/source", "application/pdf", 60)
        self.assertEqual(urlsplit(target.url).scheme, "https")
        self.assertIn("oss-public.example.com", urlsplit(target.url).netloc)


class OCRProviderContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_serverless_adapters_share_normalized_contract(self):
        calls: list[tuple[bytes, str]] = []

        async def recognizer(image: bytes, content_type: str) -> dict:
            calls.append((image, content_type))
            return {
                "text": "Account balance USD 1250",
                "confidence": 0.93,
                "bounding_boxes": [
                    {
                        "text": "USD 1250",
                        "confidence": 0.93,
                        "x": 10,
                        "y": 20,
                        "width": 80,
                        "height": 16,
                    }
                ],
            }

        providers: list[OCRProvider] = [
            AlibabaCloudOCRProvider(recognizer),
            TencentSCFOCRProvider(recognizer),
        ]
        for provider in providers:
            result = await provider.recognize(b"image-bytes", "image/png")
            self.assertEqual(result.text, "Account balance USD 1250")
            self.assertEqual(result.confidence, 0.93)
            self.assertEqual(result.bounding_boxes[0]["text"], "USD 1250")
            self.assertEqual(result.provider, provider.name)
        self.assertEqual(
            calls,
            [
                (b"image-bytes", "image/png"),
                (b"image-bytes", "image/png"),
            ],
        )

    async def test_tencent_scf_registry_boundary_fails_closed_without_invoker(self):
        provider = get_ocr_provider("tencent_scf")
        self.assertIsInstance(provider, TencentSCFOCRProvider)
        with self.assertRaisesRegex(
            RuntimeError,
            "tencent_scf_ocr_client_not_configured",
        ):
            await provider.recognize(b"image-bytes", "image/png")


class IngestionFallbackTests(unittest.TestCase):
    def test_hash_embedding_is_deterministic_and_normalized(self):
        first = local_hash_embedding("AAPL dividend USD")
        second = local_hash_embedding("AAPL dividend USD")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 384)
        self.assertAlmostEqual(math.sqrt(sum(value * value for value in first)), 1.0)

    def test_chunk_fallback_preserves_content(self):
        text = "\n".join(f"Line {index} with portfolio evidence." for index in range(200))
        chunks = split_text(text, chunk_size=80, overlap=10)
        self.assertGreater(len(chunks), 1)
        self.assertIn("portfolio evidence", chunks[0])

    def test_local_transaction_extraction_has_page_citation(self):
        result = local_structured_extraction(
            [(2, "2026-07-24 BUY AAPL 10 200 USD 2000")],
            document_type="transaction_statement",
        )
        self.assertEqual(len(result["items"]), 1)
        item = result["items"][0]
        self.assertEqual(item["transaction_type"], "buy")
        self.assertEqual(item["quantity"], "10")
        self.assertEqual(item["price"], "200")
        self.assertEqual(item["amount"], "2000")
        self.assertEqual(item["page_number"], 2)
        self.assertIn("Page 2", item["citation"])


if __name__ == "__main__":
    unittest.main()
