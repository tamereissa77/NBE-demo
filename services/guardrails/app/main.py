"""Guardrails check service (NeMo Guardrails, self-check rails on the workhorse LLM).

Demos keep their own agent loop and call this service as a gate:
  POST /check/input  {config, text}  -> {allowed, rail, latency_ms}
  POST /check/output {config, text, user?} -> same
The UI turns allowed=false into the live STOP marker (D4).
"""
import os
import time
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from nemoguardrails import LLMRails, RailsConfig
from pydantic import BaseModel

CONFIG_ROOT = os.getenv("GUARDRAILS_CONFIG_ROOT", "/config")
REFUSAL = "I'm sorry, I can't help with that."
app = FastAPI(title="NBE guardrails")


@lru_cache(maxsize=8)
def rails(config: str) -> LLMRails:
    path = os.path.join(CONFIG_ROOT, config)
    if not os.path.isdir(path):
        raise HTTPException(404, f"unknown guardrails config {config}")
    return LLMRails(RailsConfig.from_path(path))


class CheckIn(BaseModel):
    config: str = "banking"
    text: str
    user: str | None = None   # for output checks: the user turn the reply answers


def _activated(res) -> list[str]:
    log = getattr(res, "log", None)
    return [r.name for r in (log.activated_rails if log else []) if getattr(r, "stop", False)]


async def _run(config: str, messages: list[dict], which: str) -> dict:
    t = time.time()
    res = await rails(config).generate_async(messages=messages, options={"rails": [which], "log": {"activated_rails": True}})
    stopped = _activated(res)
    content = res.response[-1]["content"] if res.response else ""
    allowed = not stopped
    return {"allowed": allowed, "rail": stopped[0] if stopped else None,
            "message": None if allowed else content or REFUSAL, "latency_ms": int((time.time() - t) * 1000)}


@app.get("/health")
def health():
    return {"status": "ok", "configs": sorted(os.listdir(CONFIG_ROOT))}


@app.post("/check/input")
async def check_input(body: CheckIn):
    return await _run(body.config, [{"role": "user", "content": body.text}], "input")


@app.post("/check/output")
async def check_output(body: CheckIn):
    msgs = [{"role": "user", "content": body.user or ""}, {"role": "assistant", "content": body.text}]
    return await _run(body.config, msgs, "output")
