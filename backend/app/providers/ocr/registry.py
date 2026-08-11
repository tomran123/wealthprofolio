from app.core.config import get_settings
from app.providers.ocr.base import OCRProvider
from app.providers.ocr.tesseract import TesseractOCRProvider


def get_ocr_provider(name: str | None = None) -> OCRProvider:
    settings = get_settings()
    provider_name = (name or settings.document_ocr_provider).lower()
    if provider_name in ("auto", "tesseract", "local"):
        return TesseractOCRProvider()
    if provider_name == "aws_textract":
        from app.providers.ocr.aws_textract import AWSTextractOCRProvider

        return AWSTextractOCRProvider(settings.document_storage_region)
    if provider_name == "azure_form_recognizer":
        from app.providers.ocr.azure_form_recognizer import (
            AzureFormRecognizerOCRProvider,
        )

        return AzureFormRecognizerOCRProvider(
            getattr(settings, "document_azure_ocr_endpoint", ""),
            getattr(settings, "document_azure_ocr_key", ""),
        )
    if provider_name == "alibaba_ocr":
        from app.providers.ocr.alibaba_ocr import AlibabaCloudOCRProvider

        return AlibabaCloudOCRProvider()
    if provider_name in {"tencent_scf", "tencent_scf_ocr"}:
        from app.providers.ocr.tencent_scf import TencentSCFOCRProvider

        return TencentSCFOCRProvider()
    raise RuntimeError("unsupported_ocr_provider")
