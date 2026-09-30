"""Central configuration for the LLM Gateway.

All settings come from environment variables (see .env.example). The gateway
runs fully offline out of the box: with no keys configured it serves the mock
provider and accepts requests without client auth in local dev mode.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _model_routes(value: str) -> dict[str, str]:
    """Parse 'prefix:provider,prefix:provider' into a routing table."""
    routes: dict[str, str] = {}
    for pair in _csv(value):
        if ":" in pair:
            prefix, provider = pair.split(":", 1)
            routes[prefix.strip()] = provider.strip()
    return routes


@dataclass
class Settings:
    # --- Gateway server ---
    host: str = field(default_factory=lambda: os.getenv("GATEWAY_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("GATEWAY_PORT", "8000")))

    # --- Client auth ---
    # Comma-separated API keys accepted from gateway clients. Empty = auth
    # disabled (local development only; a warning is logged at startup).
    api_keys: list[str] = field(
        default_factory=lambda: _csv(os.getenv("GATEWAY_API_KEYS", ""))
    )

    # --- Rate limiting ---
    rate_limit_rpm: int = field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_RPM", "60"))
    )

    # --- Retry policy ---
    max_retries: int = field(default_factory=lambda: int(os.getenv("MAX_RETRIES", "3")))
    retry_base_delay: float = field(
        default_factory=lambda: float(os.getenv("RETRY_BASE_DELAY", "0.5"))
    )

    # --- Routing ---
    default_provider: str = field(
        default_factory=lambda: os.getenv("DEFAULT_PROVIDER", "mock")
    )
    model_routes: dict[str, str] = field(
        default_factory=lambda: _model_routes(
            os.getenv("MODEL_ROUTES", "mock:mock,gpt:openai,openai:openai")
        )
    )

    # --- OpenAI-compatible provider ---
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_base_url: str = field(
        default_factory=lambda: os.getenv(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        )
    )
    openai_model: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o-mini")
    )
    provider_timeout: float = field(
        default_factory=lambda: float(os.getenv("PROVIDER_TIMEOUT", "60"))
    )

    # --- Storage ---
    database_path: str = field(
        default_factory=lambda: os.getenv("DATABASE_PATH", "data/gateway.db")
    )

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_keys)


settings = Settings()
