from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TRA_", extra="ignore")

    database_url: str = "postgresql+psycopg://travelrisk:travelrisk@localhost:5433/travelrisk"
    # On AWS the URL is assembled from parts so the password can come from Secrets Manager.
    db_host: str | None = None
    db_port: int = 5432
    db_name: str = "travelrisk"
    db_user: str = "travelrisk"
    db_password: SecretStr | None = None
    # Protects operator-only endpoints such as /v1/advisories/sync (called by EventBridge).
    operator_api_key: SecretStr = SecretStr("dev-operator-key")
    http_timeout_seconds: float = 30.0
    user_agent: str = "travel-risk-agent/0.1"
    trip_retention_days: int = 30

    # "claude" needs ANTHROPIC_API_KEY (or an `ant auth login` profile).
    # "heuristic" is the offline rules-only baseline.
    # "ollama" runs a local model (no data leaves the machine).
    model_provider: Literal["claude", "ollama", "heuristic"] = "heuristic"
    # Read from ANTHROPIC_API_KEY in the environment or .env. When unset, the SDK falls back to
    # its own credential chain (e.g. an `ant auth login` profile).
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    claude_model: str = "claude-opus-5-5"
    claude_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    # Email via Amazon SES. Unset = email organisations use the log channel.
    ses_from_email: str | None = None
    aws_region: str = "eu-west-1"
    digest_hour_utc: int = 8

    # The MCP server acts as one organisation, identified by its API key.
    mcp_api_key: SecretStr | None = None

    # Used to resolve ambiguous dates such as 03/04/2026 in customer CSVs.
    csv_day_first: bool = True


    @model_validator(mode="after")
    def _assemble_database_url(self) -> "Settings":
        if self.db_host and self.db_password:
            from urllib.parse import quote

            pw = quote(self.db_password.get_secret_value(), safe="")
            self.database_url = (f"postgresql+psycopg://{self.db_user}:{pw}@{self.db_host}:"
                                 f"{self.db_port}/{self.db_name}?sslmode=require")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
