from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TRA_", extra="ignore")

    database_url: str = "postgresql+psycopg://travelrisk:travelrisk@localhost:5433/travelrisk"
    # Protects operator-only endpoints such as /v1/advisories/sync (called by EventBridge).
    operator_api_key: SecretStr = SecretStr("dev-operator-key")
    http_timeout_seconds: float = 30.0
    user_agent: str = "travel-risk-agent/0.1"
    trip_retention_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
