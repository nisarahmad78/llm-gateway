"""Seed the gateway with demo traffic so the dashboard has data.

Starts nothing itself — run the gateway first:

    uvicorn app.main:app --port 8000
    python seed_demo.py

Fires ~20 sample chat requests (a few of them streaming) at the mock
provider by default. Set GATEWAY_URL and GATEWAY_API_KEY to match your
gateway configuration.
"""

from __future__ import annotations

import os
import random

import httpx

BASE_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")
API_KEY = os.getenv("GATEWAY_API_KEY", "demo-key-123")

QUESTIONS = [
    "Explain retrieval-augmented generation in two sentences.",
    "Write a haiku about databases.",
    "What are the trade-offs between SQL and NoSQL?",
    "Give me a Python one-liner to reverse a string.",
    "Summarize the CAP theorem for a junior engineer.",
    "How does a token bucket rate limiter work?",
    "Draft a polite follow-up email after a job interview.",
    "What is the difference between latency and throughput?",
    "Explain embeddings to a product manager.",
    "List three ways to cut LLM inference cost.",
    "Turn this into JSON: name Sara, age 31, city Lahore.",
    "Why do we chunk documents before embedding them?",
    "Write a SQL query for the top 5 customers by revenue.",
    "What should an API gateway log for observability?",
    "Explain retries with exponential backoff.",
    "Give a 3-step plan to learn FastAPI.",
    "What is eventual consistency? One short example.",
    "Rewrite this politely: send me the file now.",
]


def main() -> None:
    headers = {"Authorization": f"Bearer {API_KEY}"}
    # trust_env=False: a local gateway should never be reached through a
    # proxy picked up from environment variables.
    with httpx.Client(
        base_url=BASE_URL, headers=headers, timeout=30, trust_env=False
    ) as client:
        health = client.get("/health")
        health.raise_for_status()
        print(f"Gateway health: {health.json()['status']}")

        sent = 0
        for question in QUESTIONS:
            stream = random.random() < 0.25
            payload = {
                "model": "mock-1",
                "messages": [{"role": "user", "content": question}],
                "stream": stream,
            }
            if stream:
                with client.stream(
                    "POST", "/v1/chat/completions", json=payload
                ) as response:
                    chunks = sum(1 for _ in response.iter_lines())
                print(f"[{sent + 1:2}] streamed {chunks} chunks — {question[:52]}")
            else:
                response = client.post("/v1/chat/completions", json=payload)
                response.raise_for_status()
                usage = response.json()["usage"]
                print(
                    f"[{sent + 1:2}] {usage['total_tokens']:4} tokens — {question[:52]}"
                )
            sent += 1

        print(f"\nDone: {sent} requests sent.")
        print(f"Open the dashboard: {BASE_URL}/")


if __name__ == "__main__":
    main()
