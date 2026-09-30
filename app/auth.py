"""API-key authentication for gateway clients.

Clients send `Authorization: Bearer <key>` (OpenAI style) or `x-api-key`.
Keys are configured via the GATEWAY_API_KEYS environment variable. When no
keys are configured the gateway runs in open local-dev mode.
"""

from __future__ import annotations

import hashlib

from fastapi import Header, HTTPException, status

from .config import settings


def mask_key(key: str) -> str:
    """Short, safe identifier for logs — never store raw client keys."""
    if not key:
        return "anonymous"
    digest = hashlib.sha256(key.encode()).hexdigest()[:6]
    return f"key_{digest}"


async def require_api_key(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> str:
    """FastAPI dependency. Returns a masked key id for logging."""
    if not settings.auth_enabled:
        return "open-dev-mode"
    presented = x_api_key
    if authorization and authorization.lower().startswith("bearer "):
        presented = authorization[7:].strip()
    if presented and presented in settings.api_keys:
        return mask_key(presented)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error": {
                "message": "Invalid or missing API key.",
                "type": "authentication_error",
                "code": "invalid_api_key",
            }
        },
    )
