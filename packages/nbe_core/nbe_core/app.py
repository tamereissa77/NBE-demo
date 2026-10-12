"""FastAPI app factory shared by every demo service.

Every demo gets the same /health and /info endpoints, so the portal and `make verify`
can check all seven the same way.
"""
import time

import httpx
import psycopg
from fastapi import FastAPI

from nbe_core.settings import settings


async def _check_postgres() -> str:
    try:
        async with await psycopg.AsyncConnection.connect(settings.postgres_dsn) as conn:
            await conn.execute("SELECT 1")
        return "ok"
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return f"error: {type(exc).__name__}"


async def _check_qdrant() -> str:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{settings.qdrant_url}/readyz")
        return "ok" if r.status_code == 200 else f"error: HTTP {r.status_code}"
    except Exception as exc:  # noqa: BLE001
        return f"error: {type(exc).__name__}"


def create_app(demo_id: str, title: str, phase: str = "scaffold") -> FastAPI:
    app = FastAPI(title=f"{settings.bank_short} {demo_id.upper()} · {title}", docs_url="/docs", redoc_url=None)
    started = time.time()

    @app.get("/health")
    async def health() -> dict:
        deps = {"postgres": await _check_postgres(), "qdrant": await _check_qdrant()}
        return {
            "demo": demo_id,
            "status": "ok" if all(v == "ok" for v in deps.values()) else "degraded",
            "deps": deps,
            "uptime_s": int(time.time() - started),
        }

    @app.get("/info")
    async def info() -> dict:
        return {"demo": demo_id, "title": title, "phase": phase,
                "models_wired": bool(settings.llm_gateway_url)}

    return app
