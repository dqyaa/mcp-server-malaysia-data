"""Application configuration via environment variables.

12-factor app pattern: all config from env, none from code. Pydantic-settings
auto-loads from a .env file in dev and from real env in prod/CI.

Why this matters in interviews: a hiring manager will ask "how do you handle
secrets?" and "how do you toggle features in different environments?" — having
a single typed Settings object you can show them is a strong signal.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Loaded from env vars and optional .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MALAYSIA_DATA_",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Service identity ---
    service_name: str = Field("malaysia-data-mcp", description="Service identifier in logs/traces.")
    environment: Literal["dev", "staging", "prod"] = "dev"

    # --- HTTP client ---
    http_timeout_seconds: float = Field(10.0, ge=1.0, le=60.0)
    http_max_retries: int = Field(3, ge=0, le=10)
    http_retry_min_wait_seconds: float = Field(0.5, ge=0.1)
    http_retry_max_wait_seconds: float = Field(8.0, ge=1.0)

    # --- Upstream URLs ---
    bnm_base_url: str = "https://api.bnm.gov.my/public"
    datagovmy_base_url: str = "https://api.data.gov.my"

    # --- Rate limiting (per-upstream, token-bucket) ---
    bnm_rate_limit_per_minute: int = Field(60, description="Self-imposed limit; BNM is generous.")
    datagovmy_rate_limit_per_minute: int = Field(60)

    # --- Circuit breaker ---
    circuit_failure_threshold: int = Field(5, description="Open circuit after N consecutive fails.")
    circuit_recovery_seconds: float = Field(30.0)

    # --- Cache ---
    cache_default_ttl_seconds: int = 300  # 5 min default
    cache_redis_url: str | None = Field(
        None,
        description="redis://host:port/db; if unset, L1-only cache.",
    )
    cache_l1_max_size: int = 1024

    # --- Observability ---
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = Field(True, description="Emit JSON logs (false = human-readable).")
    otel_enabled: bool = False
    otel_endpoint: str | None = Field(None, description="OTLP HTTP endpoint, e.g. http://localhost:4318")
    metrics_enabled: bool = True
    sentry_dsn: str | None = None

    # --- HTTP server (REST transport) ---
    http_host: str = "0.0.0.0"  # noqa: S104  # bind all in containers
    http_port: int = Field(8000, ge=1, le=65535)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Module-level singleton. Tests override via dependency injection."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Test helper — forces reload on next get_settings() call."""
    global _settings
    _settings = None
