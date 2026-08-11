from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application configuration, loaded from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://wealthportfolio:wealthportfolio@localhost:5432/wealthportfolio"

    # Auth
    jwt_secret: str = "change-me-in-env"
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "wealthportfolio-api"
    jwt_audience: str = "wealthportfolio-web"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days

    initial_admin_username: str = "admin"
    initial_admin_password: str = "change-me"

    # CORS (only relevant when calling the API directly, e.g. from a non-proxied client)
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # App
    default_base_currency: str = "USD"
    environment: str = "development"

    # Agent / recovery
    llm_encryption_key: str | None = None
    app_encryption_key: str | None = None
    encryption_provider: str = "local"
    alicloud_region_id: str | None = None
    alicloud_kms_key_id: str | None = None
    alicloud_kms_endpoint: str | None = None
    llm_custom_allowed_hosts: list[str] = []
    agent_max_file_bytes: int = 20 * 1024 * 1024
    agent_timezone: str = "Asia/Shanghai"
    backup_max_bytes: int = 200 * 1024 * 1024
    redis_url: str | None = None

    # Private document center / OCR / RAG
    document_max_file_bytes: int = 25 * 1024 * 1024
    document_max_pdf_pages: int = 200
    document_max_render_pixels: int = 250_000_000
    document_upload_intent_seconds: int = 15 * 60
    document_storage_backend: str = "local"  # local | minio | oss
    document_storage_local_path: str = "./data/documents"
    document_storage_endpoint: str = "http://minio:9000"
    document_storage_public_endpoint: str | None = None
    document_storage_bucket: str = "wealthportfolio-private"
    document_storage_access_key: str = ""
    document_storage_secret_key: str = ""
    document_storage_region: str | None = None
    document_storage_secure: bool = False
    document_storage_kms_key_id: str | None = None
    document_ocr_provider: str = "auto"  # auto | tesseract | cloud adapter name
    document_tesseract_command: str = "tesseract"
    document_tesseract_languages: str = "eng+chi_sim"
    document_vision_max_pages: int = 8
    document_clamav_host: str | None = None
    document_clamav_port: int = 3310
    document_clamav_required: bool = False
    document_job_backend: str = "auto"  # auto | celery | background
    document_inline_fallback: bool = True
    agent_job_backend: str = "auto"  # auto | celery | background
    agent_inline_fallback: bool = True
    price_job_backend: str = "auto"  # auto | celery | background
    price_inline_fallback: bool = True
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    @model_validator(mode="after")
    def validate_security_configuration(self) -> "Settings":
        self.environment = self.environment.strip().lower()
        self.jwt_algorithm = self.jwt_algorithm.strip().upper()
        if self.jwt_algorithm not in {"HS256", "HS384", "HS512"}:
            raise ValueError("jwt_algorithm_must_be_hmac_sha2")

        if self.environment not in {"production", "prod"}:
            return self

        weak_values = {
            "",
            "change-me",
            "change-me-in-env",
            "change-me-to-a-long-random-string",
            "wealthportfolio",
        }
        if (
            self.jwt_secret.strip().lower() in weak_values
            or len(self.jwt_secret.encode("utf-8")) < 32
        ):
            raise ValueError("production_jwt_secret_must_be_at_least_32_bytes")
        if (
            self.initial_admin_password.strip().lower() in weak_values
            or len(self.initial_admin_password) < 12
        ):
            raise ValueError("production_initial_admin_password_is_weak")
        if any(origin.strip() == "*" for origin in self.cors_origins):
            raise ValueError("production_cors_wildcard_forbidden")
        if not self.redis_url:
            raise ValueError("production_redis_url_required")
        if not self.celery_broker_url or not self.celery_result_backend:
            raise ValueError("production_celery_configuration_required")
        if any(
            backend.strip().lower() != "celery"
            for backend in (
                self.agent_job_backend,
                self.price_job_backend,
                self.document_job_backend,
            )
        ):
            raise ValueError("production_jobs_must_use_celery")
        if any(
            (
                self.agent_inline_fallback,
                self.price_inline_fallback,
                self.document_inline_fallback,
            )
        ):
            raise ValueError("production_inline_job_fallback_forbidden")
        storage_backend = self.document_storage_backend.strip().lower()
        if storage_backend not in {"minio", "oss"}:
            raise ValueError("production_private_object_storage_required")
        if storage_backend == "oss":
            required_oss_values = (
                self.document_storage_endpoint,
                self.document_storage_public_endpoint,
                self.document_storage_bucket,
                self.document_storage_access_key,
                self.document_storage_secret_key,
                self.document_storage_kms_key_id,
            )
            if any(not str(value or "").strip() for value in required_oss_values):
                raise ValueError("production_oss_configuration_required")
            if not self.document_storage_secure:
                raise ValueError("production_oss_https_required")
            private_endpoint = str(self.document_storage_endpoint).strip()
            public_endpoint = str(self.document_storage_public_endpoint).strip()
            normalized_private = (
                private_endpoint
                if "://" in private_endpoint
                else f"https://{private_endpoint}"
            )
            normalized_public = (
                public_endpoint
                if "://" in public_endpoint
                else f"https://{public_endpoint}"
            )
            parsed_private = urlsplit(normalized_private)
            parsed_public = urlsplit(normalized_public)
            if (
                parsed_private.scheme.lower() != "https"
                or not parsed_private.netloc
            ):
                raise ValueError("production_oss_private_https_required")
            if (
                parsed_public.scheme.lower() != "https"
                or not parsed_public.netloc
            ):
                raise ValueError("production_oss_public_https_required")
            if "-internal." in public_endpoint.lower():
                raise ValueError("production_oss_public_endpoint_must_be_external")
        if not self.document_clamav_required or not self.document_clamav_host:
            raise ValueError("production_clamav_required")

        provider = self.encryption_provider.strip().lower()
        if provider in {"local", "local-aesgcm"}:
            wrapping_secret = self.app_encryption_key or self.llm_encryption_key
            if (
                not wrapping_secret
                or wrapping_secret.strip().lower() in weak_values
                or len(wrapping_secret.encode("utf-8")) < 32
            ):
                raise ValueError("production_app_encryption_key_must_be_at_least_32_bytes")
        elif provider in {"alicloud", "alibaba-kms", "kms"}:
            if not self.alicloud_region_id or not self.alicloud_kms_key_id:
                raise ValueError("production_alicloud_kms_configuration_required")
        else:
            raise ValueError("unsupported_encryption_provider")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
