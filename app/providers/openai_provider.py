"""OpenAI-compatible provider.

Talks to any endpoint that speaks the OpenAI chat-completions API: OpenAI
itself, Azure OpenAI, OpenRouter, Together, Groq, a local vLLM / Ollama
server, and so on. Configure with OPENAI_API_KEY, OPENAI_BASE_URL and
LLM_MODEL.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from ..config import settings
from ..pricing import estimate_tokens
from .base import ChatResult, Provider, ProviderError, StreamChunk


class OpenAICompatibleProvider(Provider):
    name = "openai"

    def __init__(self) -> None:
        self.base_url = settings.openai_base_url.rstrip("/")
        self.api_key = settings.openai_api_key
        self.default_model = settings.openai_model
        self.timeout = settings.provider_timeout

    def models(self) -> list[str]:
        return [self.default_model]

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _payload(self, messages, model, temperature, max_tokens, stream=False) -> dict:
        payload: dict = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return payload

    async def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ChatResult:
        url = f"{self.base_url}/chat/completions"
        payload = self._payload(messages, model, temperature, max_tokens)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise ProviderError(f"Provider timed out: {exc}", status_code=504) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Provider request failed: {exc}") from exc

        if response.status_code >= 400:
            retryable = response.status_code == 429 or response.status_code >= 500
            raise ProviderError(
                f"Provider returned {response.status_code}: {response.text[:300]}",
                status_code=502,
                retryable=retryable,
            )

        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        usage = data.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        if prompt_tokens is None:
            prompt_tokens = estimate_tokens(
                "\n".join(str(m.get("content", "")) for m in messages)
            )
        if completion_tokens is None:
            completion_tokens = estimate_tokens(content)
        return ChatResult(
            content=content,
            model=data.get("model", payload["model"]),
            prompt_tokens=int(prompt_tokens),
            completion_tokens=int(completion_tokens),
            finish_reason=choice.get("finish_reason") or "stop",
            raw=data,
        )

    async def stream_chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamChunk]:
        url = f"{self.base_url}/chat/completions"
        payload = self._payload(messages, model, temperature, max_tokens, stream=True)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", url, json=payload, headers=self._headers()
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", "replace")
                        retryable = (
                            response.status_code == 429 or response.status_code >= 500
                        )
                        raise ProviderError(
                            f"Provider returned {response.status_code}: {body[:300]}",
                            status_code=502,
                            retryable=retryable,
                        )
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        choice = (chunk.get("choices") or [{}])[0]
                        delta = (choice.get("delta") or {}).get("content") or ""
                        yield StreamChunk(
                            delta=delta,
                            model=chunk.get("model", payload["model"]),
                            finish_reason=choice.get("finish_reason"),
                        )
        except httpx.TimeoutException as exc:
            raise ProviderError(f"Provider timed out: {exc}", status_code=504) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Provider request failed: {exc}") from exc
