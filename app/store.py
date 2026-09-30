"""SQLite-backed request log and statistics store.

Every gateway request is recorded here so the dashboard can show traffic,
token usage, cost and latency. SQLite keeps the demo zero-setup; the store
is a thin layer over plain SQL, so swapping in Postgres later only touches
this module.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass

_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT    NOT NULL DEFAULT (datetime('now')),
    api_key         TEXT    NOT NULL,
    model           TEXT    NOT NULL,
    provider        TEXT    NOT NULL,
    prompt_tokens   INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms      REAL    NOT NULL DEFAULT 0,
    status          TEXT    NOT NULL,
    http_status     INTEGER NOT NULL DEFAULT 200,
    estimated_cost  REAL    NOT NULL DEFAULT 0,
    stream          INTEGER NOT NULL DEFAULT 0,
    error           TEXT
);
CREATE INDEX IF NOT EXISTS idx_requests_ts ON requests(ts);
CREATE INDEX IF NOT EXISTS idx_requests_model ON requests(model);
CREATE INDEX IF NOT EXISTS idx_requests_provider ON requests(provider);
"""


@dataclass
class RequestLog:
    api_key: str
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    status: str  # "ok" | "error" | "rate_limited"
    http_status: int
    estimated_cost: float
    stream: bool = False
    error: str | None = None


class RequestStore:
    def __init__(self, path: str) -> None:
        self.path = path
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def log(self, entry: RequestLog) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO requests
                    (api_key, model, provider, prompt_tokens, completion_tokens,
                     latency_ms, status, http_status, estimated_cost, stream, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.api_key,
                    entry.model,
                    entry.provider,
                    entry.prompt_tokens,
                    entry.completion_tokens,
                    round(entry.latency_ms, 2),
                    entry.status,
                    entry.http_status,
                    entry.estimated_cost,
                    int(entry.stream),
                    entry.error,
                ),
            )
            self._conn.commit()

    def stats(self) -> dict:
        with self._lock:
            totals = self._conn.execute(
                """
                SELECT COUNT(*)                       AS total_requests,
                       COALESCE(SUM(prompt_tokens), 0)     AS prompt_tokens,
                       COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                       COALESCE(SUM(estimated_cost), 0)    AS total_cost,
                       COALESCE(AVG(latency_ms), 0)        AS avg_latency_ms,
                       COALESCE(SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END), 0) AS ok_count,
                       COALESCE(SUM(CASE WHEN status != 'ok' THEN 1 ELSE 0 END), 0) AS error_count
                FROM requests
                """
            ).fetchone()
            by_model = self._conn.execute(
                """
                SELECT model, COUNT(*) AS requests,
                       SUM(prompt_tokens + completion_tokens) AS tokens,
                       SUM(estimated_cost) AS cost
                FROM requests GROUP BY model ORDER BY requests DESC
                """
            ).fetchall()
            by_provider = self._conn.execute(
                """
                SELECT provider, COUNT(*) AS requests,
                       SUM(prompt_tokens + completion_tokens) AS tokens,
                       SUM(estimated_cost) AS cost,
                       AVG(latency_ms) AS avg_latency_ms
                FROM requests GROUP BY provider ORDER BY requests DESC
                """
            ).fetchall()
        return {
            "totals": dict(totals),
            "by_model": [dict(row) for row in by_model],
            "by_provider": [dict(row) for row in by_provider],
        }

    def recent(self, limit: int = 25) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, ts, api_key, model, provider, prompt_tokens,
                       completion_tokens, latency_ms, status, http_status,
                       estimated_cost, stream, error
                FROM requests ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
