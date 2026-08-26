"""Typed settings, read once from the environment.

Same job as zod-parsed env in the Next side: fail loudly at boot rather than
handing `undefined` to something three layers down.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Service
    app_name: str = "kitty-agent"
    environment: str = "development"

    # Where the widget calls from. Comma separated so a host env var can carry
    # several origins without any parsing ceremony at the call site.
    allowed_origins: str = "http://localhost:3000"

    # Set once the agent exists. While it is empty every /chat request gets the
    # napping fallback instead of a 500, which is the guardrail from the plan:
    # a broken agent should never be the thing a recruiter sees.
    llm_api_key: str = ""

    # Cost ceiling. Enforced for real in a later phase, declared here so the
    # limit lives in config from the start rather than being bolted on.
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
    """Cached so the env is parsed once per process, not once per request."""
    return Settings()
