"""Provider interface.

A provider turns a list of chat messages into a completion. Everything
above this layer (routing, auth, logging, rate limiting) only talks to this
interface, so adding a new vendor means writing one new class here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


class ProviderError(Exception):
    """Raised when an upstream provider call fails."""

    def __init__(self, message: str, status_code: int = 502, retryable: bool = True):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


@dataclass
class ChatResult:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str = "stop"
    raw: dict = field(default_factory=dict)


@dataclass
class StreamChunk:
    delta: str
    model: str
    finish_reason: str | None = None


class Provider(ABC):
    name: str = "base"

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ChatResult:
        """Run a non-streaming chat completion."""
        raise NotImplementedError

    @abstractmethod
    def stream_chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Yield completion chunks for a streaming response."""
        raise NotImplementedError

    @abstractmethod
    def models(self) -> list[str]:
        """Model ids this provider can serve."""
        raise NotImplementedError
