from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TRA_", extra="ignore")

    database_url: str = "postgresql+psycopg://travelrisk:travelrisk@localhost:5433/travelrisk"
    # Protects operator-only endpoints such as /v1/advisories/sync (called by EventBridge).
    operator_api_key: SecretStr = SecretStr("dev-operator-key")
    http_timeout_seconds: float = 30.0
    user_agent: str = "travel-risk-agent/0.1"
    trip_retention_days: int = 30

    # "claude" needs ANTHROPIC_API_KEY (or an `ant auth login` profile).
    # "heuristic" is the offline rules-only baseline.
    model_provider: Literal["claude", "heuristic"] = "heuristic"
    # Read from ANTHROPIC_API_KEY in the environment or .env. When unset, the SDK falls back to
    # its own credential chain (e.g. an `ant auth login` profile).
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    claude_model: str = "claude-opus-5-5"
    claude_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"

    # Used to resolve ambiguous dates such as 03/04/2026 in customer CSVs.
    csv_day_first: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
