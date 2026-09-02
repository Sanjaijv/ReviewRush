from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, validated from environment variables on startup."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")

    database_url: str = Field(
        default="postgresql+psycopg://reviewrush:reviewrush@localhost:5432/reviewrush"
    )
    redis_url: str = Field(default="redis://localhost:6379/0")
    celery_broker_url: str | None = Field(default=None)
    celery_result_backend: str | None = Field(default=None)

    github_app_id: str = Field(default="")
    github_private_key: str = Field(default="")
    github_webhook_secret: str = Field(default="")
    github_api_base_url: str = Field(default="https://api.github.com")

    @property
    def celery_broker(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def celery_backend(self) -> str:
        return self.celery_result_backend or self.redis_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
