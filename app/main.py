"""LLM Gateway API.

A single OpenAI-compatible endpoint in front of multiple LLM providers,
with API-key auth, per-key rate limiting, retries, SQLite request logging
and a built-in observability dashboard.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .auth import require_api_key
from .config import settings
from .pricing import estimate_cost, estimate_tokens
from .providers.base import ProviderError
from .ratelimit import TokenBucketLimiter
from .routing import all_models, provider_status, route, with_retry
from .store import RequestLog, RequestStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("llm_gateway")

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="LLM Gateway",
    description="Unified, observable API in front of LLM providers.",
    version="1.0.0",
)

store = RequestStore(settings.database_path)
limiter = TokenBucketLimiter(settings.rate_limit_rpm)

if not settings.auth_enabled:
    logger.warning(
        "GATEWAY_API_KEYS is empty — client auth is DISABLED (local dev mode)."
    )


# --------------------------------------------------------------------------
# Schemas (OpenAI-compatible shapes)
# --------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "mock-1"
    messages: list[ChatMessage]
    temperature: float = 0.7
    max_tokens: int | None = None
    stream: bool = False


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _error_body(message: str, error_type: str, code: str) -> dict:
    return {"error": {"message": message, "type": error_type, "code": code}}


def _completion_payload(result_model: str, content: str, prompt_tokens: int,
                        completion_tokens: int, finish_reason: str) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": result_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _enforce_rate_limit(key_id: str, model: str, provider_name: str) -> JSONResponse | None:
    allowed, retry_after = limiter.allow(key_id)
    if allowed:
        return None
    store.log(
        RequestLog(
            api_key=key_id,
            model=model,
            provider=provider_name,
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=0.0,
            status="rate_limited",
            http_status=429,
            estimated_cost=0.0,
        )
    )
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": str(max(1, round(retry_after)))},
        content=_error_body(
            "Rate limit exceeded. Slow down and retry shortly.",
            "rate_limit_error",
            "rate_limit_exceeded",
        ),
    )


# --------------------------------------------------------------------------
# API endpoints
# --------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "providers": provider_status(),
        "auth_enabled": settings.auth_enabled,
        "rate_limit_rpm": settings.rate_limit_rpm,
    }


@app.get("/v1/models", dependencies=[Depends(require_api_key)])
async def list_models() -> dict:
    return {"object": "list", "data": all_models()}


@app.post("/v1/chat/completions")
async def chat_completions(
    payload: ChatCompletionRequest,
    key_id: str = Depends(require_api_key),
):
    provider = route(payload.model)
    messages = [m.model_dump() for m in payload.messages]

    limited = _enforce_rate_limit(key_id, payload.model, provider.name)
    if limited is not None:
        return limited

    if payload.stream:
        return StreamingResponse(
            _stream_response(provider, payload, messages, key_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    started = time.perf_counter()
    try:
        result = await with_retry(
            lambda: provider.chat(
                messages, payload.model, payload.temperature, payload.max_tokens
            )
        )
    except ProviderError as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        store.log(
            RequestLog(
                api_key=key_id,
                model=payload.model,
                provider=provider.name,
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=latency_ms,
                status="error",
                http_status=exc.status_code,
                estimated_cost=0.0,
                error=str(exc)[:500],
            )
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(str(exc), "provider_error", "provider_error"),
        )

    latency_ms = (time.perf_counter() - started) * 1000
    cost = estimate_cost(result.model, result.prompt_tokens, result.completion_tokens)
    store.log(
        RequestLog(
            api_key=key_id,
            model=payload.model,
            provider=provider.name,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            latency_ms=latency_ms,
            status="ok",
            http_status=200,
            estimated_cost=cost,
        )
    )
    return _completion_payload(
        result.model,
        result.content,
        result.prompt_tokens,
        result.completion_tokens,
        result.finish_reason,
    )


async def _stream_response(
    provider, payload: ChatCompletionRequest, messages: list[dict], key_id: str
) -> AsyncIterator[str]:
    """Server-Sent Events stream in the OpenAI chunk format.

    Token usage is estimated after the stream completes (providers do not
    always report it mid-stream), then the request is logged like any other.
    """
    started = time.perf_counter()
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    collected: list[str] = []
    final_model = payload.model
    status = "ok"
    error_text: str | None = None

    def frame(delta_content: str, finish_reason: str | None = None) -> str:
        chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": final_model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": delta_content} if delta_content else {},
                    "finish_reason": finish_reason,
                }
            ],
        }
        return f"data: {json.dumps(chunk)}\n\n"

    try:
        async for chunk in provider.stream_chat(
            messages, payload.model, payload.temperature, payload.max_tokens
        ):
            final_model = chunk.model or final_model
            if chunk.delta:
                collected.append(chunk.delta)
                yield frame(chunk.delta)
            if chunk.finish_reason:
                yield frame("", finish_reason=chunk.finish_reason)
    except ProviderError as exc:
        status = "error"
        error_text = str(exc)
        yield f"data: {json.dumps(_error_body(str(exc), 'provider_error', 'provider_error'))}\n\n"
    yield "data: [DONE]\n\n"

    latency_ms = (time.perf_counter() - started) * 1000
    content = "".join(collected)
    prompt_tokens = estimate_tokens(
        "\n".join(str(m.get("content", "")) for m in messages)
    )
    completion_tokens = estimate_tokens(content)
    store.log(
        RequestLog(
            api_key=key_id,
            model=payload.model,
            provider=provider.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            status=status,
            http_status=200 if status == "ok" else 502,
            estimated_cost=estimate_cost(final_model, prompt_tokens, completion_tokens),
            stream=True,
            error=error_text[:500] if error_text else None,
        )
    )


# --------------------------------------------------------------------------
# Dashboard (observability UI + its JSON feeds)
# --------------------------------------------------------------------------


@app.get("/api/stats")
async def dashboard_stats() -> dict:
    return store.stats()


@app.get("/api/requests")
async def dashboard_requests(limit: int = 25) -> dict:
    return {"data": store.recent(limit=min(limit, 200))}


@app.get("/")
async def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "dashboard.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
