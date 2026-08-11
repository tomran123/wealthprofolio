import asyncio

from app.providers.ocr.base import OCRProvider, OCRResult


class AWSTextractOCRProvider(OCRProvider):
    name = "aws_textract"

    def __init__(self, region: str | None = None) -> None:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - deployment-specific
            raise RuntimeError("boto3_not_installed") from exc
        self.client = boto3.client("textract", region_name=region)

    async def recognize(self, image: bytes, content_type: str = "image/png") -> OCRResult:
        response = await asyncio.to_thread(
            self.client.detect_document_text,
            Document={"Bytes": image},
        )
        lines, boxes, confidences = [], [], []
        for block in response.get("Blocks", []):
            if block.get("BlockType") != "LINE":
                continue
            text = str(block.get("Text") or "").strip()
            if not text:
                continue
            confidence = float(block.get("Confidence") or 0) / 100
            lines.append(text)
            confidences.append(confidence)
            boxes.append(
                {
                    "text": text,
                    "confidence": confidence,
                    "bounding_box": (block.get("Geometry") or {}).get("BoundingBox"),
                }
            )
        return OCRResult(
            text="\n".join(lines),
            confidence=sum(confidences) / len(confidences) if confidences else None,
            bounding_boxes=boxes,
            provider=self.name,
        )
