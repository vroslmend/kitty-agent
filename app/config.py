"""Typed settings, read once from the environment."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "kitty-agent"
    environment: str = "development"

    allowed_origins: str = "http://localhost:3000"

    # An empty key is a supported state, not a misconfiguration. It puts /chat
    # into the napping fallback instead of failing, so do not assert on it.
    llm_api_key: str = ""

    max_tokens_per_request: int = 2048
    rate_limit_per_minute: int = 10

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def agent_ready(self) -> bool:
        return bool(self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    """Cached so the environment is parsed once per process, not once per request."""
    return Settings()
