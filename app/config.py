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

    # Free-tier quota is per model per day, and it is small on the newest ones:
    # gemini-3.7-flash allows 20 requests a day, which one eval run exhausts.
    # Check the real numbers at https://aistudio.google.com/rate-limit before
    # changing this. The eval harness decides which model is actually best.
    llm_model: str = "gemini-3.5-flash"

    # Neon. Carries the checkpointer, the interrupt resume state and pgvector.
    database_url: str = ""

    github_username: str = "vroslmend"
    # Unauthenticated GitHub is 60 requests an hour, which one impatient visitor
    # can exhaust. A token raises it to 5000 and needs no scopes for public data.
    github_token: str = ""

    # The Spotify credentials live in portfolio-v2, which already proxies them.
    # Pointing at that endpoint keeps one copy of the refresh token, not two.
    now_playing_url: str = ""

    site_base_url: str = "https://ammarhassan.dev"

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
