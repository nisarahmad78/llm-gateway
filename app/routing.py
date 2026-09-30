"""Routing and retry policy.

Routing: the provider for a request is chosen by matching the model name
against MODEL_ROUTES prefixes (longest prefix wins); unmatched models fall
back to DEFAULT_PROVIDER.

Retry: provider calls are retried with exponential backoff + jitter when the
provider reports a retryable error (timeouts, 429, 5xx).
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from .config import settings
from .providers.base import Provider, ProviderError
from .providers.mock import MockProvider
from .providers.openai_provider import OpenAICompatibleProvider

logger = logging.getLogger("llm_gateway.routing")

_PROVIDERS: dict[str, Provider] = {
    "mock": MockProvider(),
    "openai": OpenAICompatibleProvider(),
}

T = TypeVar("T")


def get_provider(name: str) -> Provider:
    provider = _PROVIDERS.get(name)
    if provider is None:
        raise ProviderError(
            f"Unknown provider '{name}'. Available: {', '.join(_PROVIDERS)}",
            status_code=500,
            retryable=False,
        )
    return provider


def route(model: str) -> Provider:
    """Pick the provider responsible for a model id."""
    best_prefix = ""
    chosen: str | None = None
    for prefix, provider_name in settings.model_routes.items():
        if model.startswith(prefix) and len(prefix) > len(best_prefix):
            best_prefix = prefix
            chosen = provider_name
    return get_provider(chosen or settings.default_provider)


def all_models() -> list[dict]:
    models: list[dict] = []
    seen: set[str] = set()
    for provider in _PROVIDERS.values():
        for model_id in provider.models():
            if model_id not in seen:
                seen.add(model_id)
                models.append(
                    {
                        "id": model_id,
                        "object": "model",
                        "owned_by": provider.name,
                    }
                )
    return models


def provider_status() -> dict[str, str]:
    status: dict[str, str] = {}
    for name, provider in _PROVIDERS.items():
        if name == "openai" and not settings.openai_api_key:
            status[name] = "not_configured"
        else:
            status[name] = "ready"
    return status


async def with_retry(operation: Callable[[], Awaitable[T]]) -> T:
    """Run `operation`, retrying retryable provider errors with backoff."""
    attempt = 0
    while True:
        try:
            return await operation()
        except ProviderError as exc:
            attempt += 1
            if not exc.retryable or attempt > settings.max_retries:
                raise
            delay = settings.retry_base_delay * (2 ** (attempt - 1))
            delay += random.uniform(0, 0.1 * delay)  # jitter
            logger.warning(
                "Provider error (attempt %s/%s): %s — retrying in %.2fs",
                attempt,
                settings.max_retries,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
