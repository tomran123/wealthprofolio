from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application configuration, loaded from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://wealthportfolio:wealthportfolio@localhost:5432/wealthportfolio"

    # Auth
    jwt_secret: str = "change-me-in-env"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days

    initial_admin_username: str = "admin"
    initial_admin_password: str = "change-me"

    # CORS (only relevant when calling the API directly, e.g. from a non-proxied client)
    cors_origins: list[str] = ["http://localhost:3000"]

    # App
    default_base_currency: str = "USD"
    environment: str = "development"

    # Agent / recovery
    llm_encryption_key: str | None = None
    agent_max_file_bytes: int = 20 * 1024 * 1024
    agent_timezone: str = "Asia/Shanghai"
    backup_max_bytes: int = 200 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
