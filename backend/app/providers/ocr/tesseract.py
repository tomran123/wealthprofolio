import asyncio
import csv
import io
import subprocess
import tempfile
from pathlib import Path

from app.core.config import get_settings
from app.providers.ocr.base import OCRProvider, OCRResult

settings = get_settings()


class TesseractOCRProvider(OCRProvider):
    name = "tesseract"

    def _recognize(self, image: bytes, content_type: str) -> OCRResult:
        suffix = {
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
        }.get(content_type, ".png")
        with tempfile.TemporaryDirectory(prefix="wp-ocr-") as directory:
            source = Path(directory) / f"page{suffix}"
            source.write_bytes(image)
            languages = settings.document_tesseract_languages
            command = [
                settings.document_tesseract_command,
                str(source),
                "stdout",
                "-l",
                languages,
                "--psm",
                "6",
                "tsv",
            ]
            try:
                result = subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    timeout=60,
                )
            except (FileNotFoundError, subprocess.CalledProcessError):
                if languages == "eng":
                    raise RuntimeError("tesseract_unavailable") from None
                command[command.index(languages)] = "eng"
                try:
                    result = subprocess.run(
                        command,
                        check=True,
                        capture_output=True,
                        timeout=60,
                    )
                except (FileNotFoundError, subprocess.CalledProcessError) as exc:
                    raise RuntimeError("tesseract_unavailable") from exc
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("tesseract_timeout") from exc

        rows = csv.DictReader(io.StringIO(result.stdout.decode("utf-8", errors="replace")), delimiter="\t")
        lines: dict[tuple[str, str, str], list[str]] = {}
        confidences: list[float] = []
        boxes: list[dict] = []
        for row in rows:
            text = (row.get("text") or "").strip()
            try:
                confidence = float(row.get("conf") or -1)
            except ValueError:
                confidence = -1
            if not text or confidence < 0:
                continue
            line_key = (
                row.get("block_num") or "0",
                row.get("par_num") or "0",
                row.get("line_num") or "0",
            )
            lines.setdefault(line_key, []).append(text)
            confidences.append(confidence / 100)
            try:
                boxes.append(
                    {
                        "text": text,
                        "confidence": confidence / 100,
                        "x": int(row.get("left") or 0),
                        "y": int(row.get("top") or 0),
                        "width": int(row.get("width") or 0),
                        "height": int(row.get("height") or 0),
                    }
                )
            except ValueError:
                continue
        return OCRResult(
            text="\n".join(" ".join(words) for words in lines.values()),
            confidence=(sum(confidences) / len(confidences)) if confidences else None,
            bounding_boxes=boxes,
            provider=self.name,
        )

    async def recognize(self, image: bytes, content_type: str = "image/png") -> OCRResult:
        return await asyncio.to_thread(self._recognize, image, content_type)
