"""Built-in mock provider.

Needs no API keys and no network, so the whole gateway — routing, auth,
rate limiting, logging, dashboard, streaming — can be demoed offline.
It returns a canned but context-aware reply, estimates token usage, and
simulates realistic latency.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator

from ..pricing import estimate_tokens
from .base import ChatResult, Provider, StreamChunk

MODEL_ID = "mock-1"


class MockProvider(Provider):
    name = "mock"

    def models(self) -> list[str]:
        return [MODEL_ID]

    def _build_reply(self, messages: list[dict]) -> str:
        last_user = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        snippet = " ".join(str(last_user).split())[:120]
        return (
            f"[mock provider] You asked: \"{snippet}\". "
            "This is a canned response from the built-in mock provider, so the "
            "gateway can be demoed end to end with no API keys. Point the "
            "gateway at a real model by setting OPENAI_API_KEY and routing a "
            "model such as gpt-4o-mini to the openai provider."
        )

    async def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ChatResult:
        await asyncio.sleep(random.uniform(0.05, 0.25))  # simulated latency
        reply = self._build_reply(messages)
        prompt_text = "\n".join(str(m.get("content", "")) for m in messages)
        return ChatResult(
            content=reply,
            model=model or MODEL_ID,
            prompt_tokens=estimate_tokens(prompt_text),
            completion_tokens=estimate_tokens(reply),
        )

    async def stream_chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamChunk]:
        reply = self._build_reply(messages)
        words = reply.split(" ")
        for index, word in enumerate(words):
            piece = word if index == 0 else " " + word
            await asyncio.sleep(0.02)  # simulated token pacing
            yield StreamChunk(delta=piece, model=model or MODEL_ID)
        yield StreamChunk(delta="", model=model or MODEL_ID, finish_reason="stop")
