"""Audit log: every model call, tool call and human decision lands in audit.events."""
import json

import psycopg

from nbe_core.settings import settings


async def log_event(kind: str, actor: str | None = None, payload: dict | None = None,
                    session_id: str | None = None, latency_ms: int | None = None) -> None:
    async with await psycopg.AsyncConnection.connect(settings.postgres_dsn) as conn:
        await conn.execute(
            "INSERT INTO audit.events (demo, session_id, kind, actor, payload, latency_ms) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (settings.demo_id, session_id, kind, actor, json.dumps(payload or {}), latency_ms),
        )
