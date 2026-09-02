from functools import lru_cache

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    upstream_base_url: AnyHttpUrl = "https://api.openai.com/v1"
    upstream_api_key: SecretStr
    inbound_api_keys: frozenset[str] = Field(min_length=1)
    allowed_models: frozenset[str] = frozenset({"gpt-4o-mini"})
    request_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    max_retries: int = Field(default=2, ge=0, le=5)
    max_messages: int = Field(default=50, ge=1, le=200)

    @field_validator("inbound_api_keys", "allowed_models", mode="before")
    @classmethod
    def parse_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return frozenset(item.strip() for item in value.split(",") if item.strip())
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

