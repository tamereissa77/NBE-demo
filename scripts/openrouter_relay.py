"""Local stand-in for the LiteLLM gateway, for laptop runs without the GB10 model servers.

Sends each alias to the same Gemma 4 model the GB10 serves for it, through OpenRouter. Key: OPENROUTER_API_KEY.
OPENROUTER_FREE=1 uses the rate-limited :free variants.
VLLM_URL=http://host:8000/v1 sends every alias to that vLLM server's Gemma 4 26B instead (no key needed).
Run:
    python scripts/openrouter_relay.py        # listens on 127.0.0.1:4000
then start a demo with LLM_GATEWAY_URL=http://127.0.0.1:4000/v1
"""
import asyncio
import os

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

VLLM_URL = os.getenv("VLLM_URL", "").rstrip("/")
if VLLM_URL:
    UPSTREAM = VLLM_URL
    KEY = os.getenv("VLLM_API_KEY", "none")
    # One server, one model (docker-compose.yml: nbe-llm); "quality" has no 31B behind it here
    ALIASES = dict.fromkeys(("workhorse", "vision", "quality"), os.getenv("VLLM_MODEL", "gemma-4-26b-a4b"))
else:
    UPSTREAM = "https://openrouter.ai/api/v1"
    KEY = os.environ["OPENROUTER_API_KEY"]
    _free = ":free" if os.getenv("OPENROUTER_FREE") == "1" else ""
    # Same models as the GB10 aliases (docker-compose.yml: nbe-llm, nbe-llm-q)
    ALIASES = {"workhorse": f"google/gemma-4-26b-a4b-it{_free}", "vision": f"google/gemma-4-26b-a4b-it{_free}",
               "quality": f"google/gemma-4-31b-it{_free}"}
DEFAULT = ALIASES["workhorse"]

MAX_RETRIES = 8
# Demos fan out (D5 compares 12 articles at once); this caps how many requests go upstream together.
GATE = asyncio.Semaphore(int(os.getenv("RELAY_CONCURRENCY", "12")))

app = FastAPI()


def _retry_after(r: httpx.Response) -> float:
    if r.headers.get("retry-after", "").isdigit():
        return min(float(r.headers["retry-after"]) + 1, 65)
    return 15


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    body["model"] = ALIASES.get(body.get("model"), DEFAULT)
    if not VLLM_URL:
        # Only route to hosts that honour every parameter sent (json_schema, temperature)
        body["provider"] = {"require_parameters": True}
    # Rate limits (429) and overloaded hosts (502/503) are waited out. A hung request is cut at UPSTREAM_TIMEOUT
    # and retried, and the whole request gets REQUEST_BUDGET seconds; past that the relay answers 504 so the
    # demo can move on (D5 then retries that article on the fallback model or marks it unchecked).
    per_try = float(os.getenv("UPSTREAM_TIMEOUT", "60"))
    budget = float(os.getenv("REQUEST_BUDGET", "180"))
    headers = {"x-litellm-model-api-base": f"{UPSTREAM} ({body['model']})"}
    async with GATE, httpx.AsyncClient() as client:
        deadline = asyncio.get_running_loop().time() + budget
        for attempt in range(MAX_RETRIES):
            left = deadline - asyncio.get_running_loop().time()
            if left <= 1:
                break
            try:
                r = await client.post(f"{UPSTREAM}/chat/completions", json=body, headers={"Authorization": f"Bearer {KEY}"},
                                      timeout=httpx.Timeout(min(per_try, left), connect=10))
            except httpx.TransportError as exc:          # timeouts and dropped connections
                print(f"upstream {type(exc).__name__}, retry {attempt + 1}/{MAX_RETRIES}", flush=True)
                await asyncio.sleep(min(5, max(deadline - asyncio.get_running_loop().time(), 0)))
                continue
            if r.status_code not in (429, 502, 503):
                if os.getenv("RELAY_TIMING") == "1":
                    took = budget - (deadline - asyncio.get_running_loop().time())
                    print(f"{body['model']} {r.status_code} {took:.1f}s max_tokens={body.get('max_tokens')}", flush=True)
                return JSONResponse(r.json(), status_code=r.status_code, headers=headers)
            print(f"upstream {r.status_code}, retry {attempt + 1}/{MAX_RETRIES}", flush=True)
            await asyncio.sleep(min(_retry_after(r), max(deadline - asyncio.get_running_loop().time(), 0)))
    print(f"gave up after {budget:.0f}s ({body['model']})", flush=True)
    return JSONResponse({"error": {"message": f"upstream did not answer within {budget:.0f}s"}}, status_code=504,
                        headers=headers)


if __name__ == "__main__":
    print(f"relay -> {UPSTREAM} {ALIASES}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("RELAY_PORT", "4000")))
