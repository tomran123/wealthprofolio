import hashlib
import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.models.document import EMBEDDING_DIMENSIONS


@dataclass(frozen=True, slots=True)
class RenderedPage:
    page_number: int
    image: bytes
    content_type: str
    width: int
    height: int
    embedded_text: str


def render_document_pages(content: bytes, content_type: str) -> list[RenderedPage]:
    import fitz

    filetype = "pdf" if content_type == "application/pdf" else content_type.split("/", 1)[1]
    document = fitz.open(stream=content, filetype=filetype)
    try:
        pages: list[RenderedPage] = []
        matrix = fitz.Matrix(1.5, 1.5)
        for index, page in enumerate(document, start=1):
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            pages.append(
                RenderedPage(
                    page_number=index,
                    image=pixmap.tobytes("png"),
                    content_type="image/png",
                    width=pixmap.width,
                    height=pixmap.height,
                    embedded_text=page.get_text("text").strip()
                    if content_type == "application/pdf"
                    else "",
                )
            )
        return pages
    finally:
        document.close()


def render_document_page(
    content: bytes,
    content_type: str,
    page_number: int,
) -> RenderedPage:
    """Render one page at a time so a compressed PDF cannot exhaust worker RAM."""

    import fitz

    filetype = "pdf" if content_type == "application/pdf" else content_type.split("/", 1)[1]
    document = fitz.open(stream=content, filetype=filetype)
    try:
        if page_number < 1 or page_number > len(document):
            raise ValueError("document_page_out_of_range")
        page = document[page_number - 1]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        return RenderedPage(
            page_number=page_number,
            image=pixmap.tobytes("png"),
            content_type="image/png",
            width=pixmap.width,
            height=pixmap.height,
            embedded_text=page.get_text("text").strip()
            if content_type == "application/pdf"
            else "",
        )
    finally:
        document.close()


def split_text(text: str, chunk_size: int = 420, overlap: int = 50) -> list[str]:
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not normalized:
        return []
    try:
        from llama_index.core.node_parser import SentenceSplitter

        splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
        chunks = [chunk.strip() for chunk in splitter.split_text(normalized) if chunk.strip()]
        if chunks:
            return chunks
    except (ImportError, ValueError):
        pass

    # Import-free deterministic fallback. Approximate four characters per token
    # while preferring paragraph boundaries.
    target, carry = chunk_size * 4, overlap * 4
    paragraphs = normalized.split("\n")
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n{paragraph}".strip()
        if current and len(candidate) > target:
            chunks.append(current)
            current = f"{current[-carry:]}\n{paragraph}".strip()
        else:
            current = candidate
        while len(current) > target * 2:
            chunks.append(current[:target])
            current = current[max(0, target - carry) :]
    if current:
        chunks.append(current)
    return chunks


def local_hash_embedding(text: str, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    """Deterministic offline embedding used when no external embedding service exists."""

    vector = [0.0] * dimensions
    tokens = re.findall(r"[\w\u3400-\u9fff]+", text.casefold())
    cjk_sequences = re.findall(r"[\u3400-\u9fff]{2,}", text)
    tokens.extend(
        sequence[index : index + 2]
        for sequence in cjk_sequences
        for index in range(len(sequence) - 1)
    )
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign * (1.0 + min(len(token), 12) / 12)
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude:
        vector = [value / magnitude for value in vector]
    return vector


TRANSACTION_WORDS = {
    "buy": ("buy", "bought", "purchase", "买入", "购买"),
    "sell": ("sell", "sold", "卖出"),
    "deposit": ("deposit", "credit", "存入", "入金"),
    "withdraw": ("withdraw", "debit", "取款", "出金"),
    "dividend": ("dividend", "股息", "分红"),
    "interest": ("interest", "利息"),
    "fee": ("fee", "commission", "手续费", "佣金"),
    "transfer": ("transfer", "转账", "转入", "转出"),
}
DATE_PATTERN = re.compile(r"\b(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}/\d{1,2}/20\d{2})\b")
CURRENCY_PATTERN = re.compile(r"\b(USD|HKD|CNY|RMB|EUR|GBP|JPY|SGD|AUD|CAD|CHF)\b", re.IGNORECASE)
NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])[-+]?\(?\d[\d,]*(?:\.\d+)?\)?")
SYMBOL_PATTERN = re.compile(r"\b[A-Z][A-Z0-9.-]{0,9}\b")


def _number(value: str) -> str | None:
    normalized = value.replace(",", "").replace("(", "-").replace(")", "")
    try:
        return format(Decimal(normalized), "f")
    except InvalidOperation:
        return None


def _date(value: str | None) -> str | None:
    if not value:
        return None
    parts = re.split(r"[-/.]", value)
    if len(parts) != 3:
        return None
    if len(parts[0]) == 4:
        year, month, day = parts
    else:
        month, day, year = parts
    try:
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    except ValueError:
        return None


def _citation(page_number: int, line: str) -> str:
    compact = " ".join(line.split())
    return f"Page {page_number}: {compact[:220]}"


def local_structured_extraction(
    pages: list[tuple[int, str]],
    *,
    document_type: str | None,
) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    warnings: list[str] = []
    for page_number, page_text in pages:
        for line in page_text.splitlines():
            normalized = " ".join(line.split())
            lowered = normalized.casefold()
            transaction_type = next(
                (
                    kind
                    for kind, words in TRANSACTION_WORDS.items()
                    if any(word.casefold() in lowered for word in words)
                ),
                None,
            )
            if transaction_type is None:
                continue
            date_match = DATE_PATTERN.search(normalized)
            currency_match = CURRENCY_PATTERN.search(normalized)
            numeric_source = (
                normalized[: date_match.start()] + normalized[date_match.end() :]
                if date_match
                else normalized
            )
            numbers = [
                number
                for match in NUMBER_PATTERN.findall(numeric_source)
                if (number := _number(match)) is not None
            ]
            symbols = [
                symbol
                for symbol in SYMBOL_PATTERN.findall(normalized)
                if symbol.upper()
                not in {
                    "BUY",
                    "SELL",
                    "USD",
                    "HKD",
                    "CNY",
                    "RMB",
                    "EUR",
                    "GBP",
                    "FEE",
                }
            ]
            currency = (currency_match.group(1).upper() if currency_match else "USD").replace(
                "RMB", "CNY"
            )
            quantity = price = amount = None
            if transaction_type in ("buy", "sell"):
                quantity = numbers[0] if numbers else None
                price = numbers[1] if len(numbers) > 1 else None
                if len(numbers) > 2:
                    amount = numbers[-1]
                elif quantity and price:
                    amount = format(Decimal(quantity) * Decimal(price), "f")
            else:
                amount = numbers[-1] if numbers else None
            confidence = 0.68 if date_match and numbers else 0.52
            citation = _citation(page_number, normalized)
            item = {
                "transaction_type": transaction_type,
                "instrument": symbols[0] if symbols else None,
                "symbol": symbols[0] if symbols else None,
                "quantity": quantity,
                "price": price,
                "amount": amount,
                "currency": currency,
                "date": _date(date_match.group(1) if date_match else None),
                "fee": None,
                "account": None,
                "note": normalized[:300],
                "confidence": confidence,
                "page_number": page_number,
                "citation": citation,
            }
            items.append(item)
            for name in ("transaction_type", "symbol", "quantity", "price", "amount", "currency", "date"):
                value = item.get(name)
                if value is None:
                    continue
                fields.append(
                    {
                        "name": f"items.{len(items) - 1}.{name}",
                        "label": name.replace("_", " ").title(),
                        "value": value,
                        "confidence": confidence,
                        "page_number": page_number,
                        "citation": citation,
                        "bounding_box": None,
                    }
                )
    if not items:
        warnings.append("No transaction-like rows were detected by the local fallback.")
    if any(float(item["confidence"]) < 0.65 for item in items):
        warnings.append("Low-confidence values require manual review.")
    return {
        "summary": (
            f"Extracted {len(items)} candidate transaction rows"
            if items
            else "Document text indexed; no candidate transactions detected"
        ),
        "document_type": document_type or "unknown",
        "fields": fields,
        "items": items,
        "warnings": warnings,
        "confidence": (
            sum(float(item["confidence"]) for item in items) / len(items) if items else None
        ),
    }


def enrich_vision_extraction(
    payload: dict[str, Any],
    pages: list[tuple[int, str]],
) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(payload.get("items") or []):
        if not isinstance(raw, dict):
            continue
        needles = [
            str(raw.get(key) or "").strip()
            for key in ("symbol", "instrument", "date")
            if raw.get(key)
        ]
        page_number = next(
            (
                number
                for number, text in pages
                if any(needle.casefold() in text.casefold() for needle in needles)
            ),
            pages[0][0] if pages else 1,
        )
        page_text = next((text for number, text in pages if number == page_number), "")
        citation = _citation(page_number, page_text[:220] or "Vision extraction")
        item = {
            **raw,
            "confidence": 0.76,
            "page_number": page_number,
            "citation": citation,
        }
        items.append(item)
        for name, value in raw.items():
            if value is None:
                continue
            fields.append(
                {
                    "name": f"items.{index}.{name}",
                    "label": name.replace("_", " ").title(),
                    "value": value,
                    "confidence": 0.76,
                    "page_number": page_number,
                    "citation": citation,
                    "bounding_box": None,
                }
            )
    for name in ("institution", "account", "document_type"):
        value = payload.get(name)
        if value is not None:
            fields.insert(
                0,
                {
                    "name": name,
                    "label": name.replace("_", " ").title(),
                    "value": value,
                    "confidence": 0.76,
                    "page_number": 1,
                    "citation": "Page 1: Vision extraction",
                    "bounding_box": None,
                },
            )
    warnings = list(payload.get("warnings") or [])
    return {
        "summary": f"Vision extracted {len(items)} candidate transaction rows",
        "document_type": payload.get("document_type") or "unknown",
        "institution": payload.get("institution"),
        "account": payload.get("account"),
        "fields": fields,
        "items": items,
        "warnings": warnings,
        "confidence": 0.76 if fields else None,
    }
