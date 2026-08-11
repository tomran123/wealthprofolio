from collections.abc import Awaitable, Callable

from app.providers.ocr.base import OCRProvider, OCRResult


class TencentSCFOCRProvider(OCRProvider):
    """Adapter boundary for a Tencent Cloud SCF-backed OCR invoker.

    A deployment-specific callable owns TC3 signing, SCF invocation, retries,
    and secret retrieval. Keeping those concerns outside this provider makes
    the OCR pipeline cloud-neutral and permits contract testing without Tencent
    credentials or network access.
    """

    name = "tencent_scf"

    def __init__(
        self,
        recognizer: Callable[[bytes, str], Awaitable[dict]] | None = None,
    ) -> None:
        self.recognizer = recognizer

    async def recognize(self, image: bytes, content_type: str = "image/png") -> OCRResult:
        if self.recognizer is None:
            raise RuntimeError("tencent_scf_ocr_client_not_configured")
        payload = await self.recognizer(image, content_type)
        return OCRResult(
            text=str(payload.get("text") or ""),
            confidence=payload.get("confidence"),
            bounding_boxes=list(payload.get("bounding_boxes") or []),
            provider=self.name,
        )
