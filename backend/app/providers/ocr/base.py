from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class OCRResult:
    text: str
    confidence: float | None
    bounding_boxes: list[dict] = field(default_factory=list)
    provider: str = "unknown"


class OCRProvider(ABC):
    name: str

    @abstractmethod
    async def recognize(self, image: bytes, content_type: str = "image/png") -> OCRResult:
        raise NotImplementedError
