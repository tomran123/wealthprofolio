import asyncio

import httpx

from app.providers.ocr.base import OCRProvider, OCRResult


class AzureFormRecognizerOCRProvider(OCRProvider):
    name = "azure_form_recognizer"

    def __init__(self, endpoint: str, api_key: str) -> None:
        if not endpoint or not api_key:
            raise RuntimeError("azure_ocr_not_configured")
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key

    async def recognize(self, image: bytes, content_type: str = "image/png") -> OCRResult:
        url = (
            f"{self.endpoint}/formrecognizer/documentModels/prebuilt-read:analyze"
            "?api-version=2023-07-31"
        )
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": content_type,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, headers=headers, content=image)
            response.raise_for_status()
            operation_url = response.headers.get("operation-location")
            if not operation_url:
                raise RuntimeError("azure_ocr_missing_operation")
            payload = {}
            for _ in range(30):
                await asyncio.sleep(1)
                poll = await client.get(
                    operation_url,
                    headers={"Ocp-Apim-Subscription-Key": self.api_key},
                )
                poll.raise_for_status()
                payload = poll.json()
                if payload.get("status") in ("succeeded", "failed"):
                    break
        if payload.get("status") != "succeeded":
            raise RuntimeError("azure_ocr_failed")
        lines, boxes, confidences = [], [], []
        for page in (payload.get("analyzeResult") or {}).get("pages", []):
            for line in page.get("lines", []):
                text = str(line.get("content") or "").strip()
                if not text:
                    continue
                confidence = line.get("confidence")
                lines.append(text)
                if confidence is not None:
                    confidences.append(float(confidence))
                boxes.append(
                    {
                        "text": text,
                        "confidence": confidence,
                        "polygon": line.get("polygon") or [],
                    }
                )
        return OCRResult(
            text="\n".join(lines),
            confidence=sum(confidences) / len(confidences) if confidences else None,
            bounding_boxes=boxes,
            provider=self.name,
        )
