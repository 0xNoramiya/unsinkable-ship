from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    tfy_api_key: str = Field(...)
    tfy_host: str = Field(...)
    tfy_gateway_base_url: str | None = None
    unsinkable_default_model: str = "resilient-chat/resilient-chat"
    unsinkable_dashboard_url: str | None = "http://127.0.0.1:8765"

    @property
    def gateway_base_url(self) -> str:
        return self.tfy_gateway_base_url or f"{self.tfy_host.rstrip('/')}/api/llm"

    @property
    def openai_base_url(self) -> str:
        return f"{self.gateway_base_url.rstrip('/')}/openai/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
