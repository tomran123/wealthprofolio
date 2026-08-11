from collections.abc import Awaitable, Callable

from app.providers.ocr.base import OCRProvider, OCRResult


class AlibabaCloudOCRProvider(OCRProvider):
    """Adapter boundary for Alibaba Cloud OCR Function Compute/OpenAPI clients.

    Production injects a signer-aware callable so credentials stay in KMS/FC
    rather than application rows. The callable returns normalized OCR data.
    """

    name = "alibaba_ocr"

    def __init__(
        self,
        recognizer: Callable[[bytes, str], Awaitable[dict]] | None = None,
    ) -> None:
        self.recognizer = recognizer

    async def recognize(self, image: bytes, content_type: str = "image/png") -> OCRResult:
        if self.recognizer is None:
            raise RuntimeError("alibaba_ocr_client_not_configured")
        payload = await self.recognizer(image, content_type)
        return OCRResult(
            text=str(payload.get("text") or ""),
            confidence=payload.get("confidence"),
            bounding_boxes=list(payload.get("bounding_boxes") or []),
            provider=self.name,
        )
