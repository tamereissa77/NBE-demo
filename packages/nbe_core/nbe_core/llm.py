"""LLM client: every demo talks to models through the LiteLLM gateway by alias
(workhorse | vision | quality | hero | embed), never to a model server directly.

Each call returns the text plus the metadata the "Show the work" drawer needs:
which model actually answered (fallbacks included), tokens, latency and tokens/s.
"""
import json
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx

from nbe_core.settings import settings

_TIMEOUT = httpx.Timeout(600, connect=5)


@dataclass
class LLMResult:
    text: str
    alias: str
    model: str                      # the model that actually answered (differs from alias on fallback)
    latency_ms: int
    served_by: str = ""             # model server URL, e.g. http://nbe-llm:8000/v1
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls: list[dict] = field(default_factory=list)

    @property
    def tokens_per_s(self) -> float:
        return round(self.completion_tokens / max(self.latency_ms / 1000, 1e-3), 1)

    def meta(self) -> dict:
        return {"alias": self.alias, "model": self.model, "served_by": self.served_by,
                "fallback": self.model != self.alias, "latency_ms": self.latency_ms,
                "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
                "tokens_per_s": self.tokens_per_s}


_CHANNEL = re.compile(r"^\s*(?:<\|?channel\|?>)?\s*thought\b.*?<channel\|>", re.S)


def clean_text(text: str) -> str:
    """Gemma 4 sometimes leaks its thinking channel ("thought ... <channel|>") into content after tool calls."""
    if "<channel|>" in text:
        text = text.rsplit("<channel|>", 1)[-1]
    return _CHANNEL.sub("", text).strip()


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.llm_gateway_key}"}


async def chat(messages: list[dict], alias: str = "workhorse", *, tools: list[dict] | None = None,
               json_schema: dict | None = None, max_tokens: int = 1024, temperature: float = 0.2,
               **extra) -> LLMResult:
    body: dict = {"model": alias, "messages": messages, "max_tokens": max_tokens, "temperature": temperature, **extra}
    if tools:
        body["tools"] = tools
    if json_schema:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "output", "schema": json_schema}}
    t = time.time()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(f"{settings.llm_gateway_url}/chat/completions", json=body, headers=_headers())
        r.raise_for_status()
        d = r.json()
    msg = d["choices"][0]["message"]
    usage = d.get("usage") or {}
    # LiteLLM reports the alias on a direct hit and the underlying model name on a fallback;
    # the api-base header says which server actually answered.
    model = d.get("model", alias)
    served_by = r.headers.get("x-litellm-model-api-base", "")
    return LLMResult(text=clean_text(msg.get("content") or ""), alias=alias, model=model, served_by=served_by,
                     latency_ms=int((time.time() - t) * 1000),
                     prompt_tokens=usage.get("prompt_tokens", 0), completion_tokens=usage.get("completion_tokens", 0),
                     tool_calls=msg.get("tool_calls") or [])


class JSONOutputError(ValueError):
    """The model's structured output did not parse; `raw` holds the text for diagnosis."""

    def __init__(self, msg: str, raw: str):
        super().__init__(msg)
        self.raw = raw


async def chat_json(messages: list[dict], schema: dict, alias: str = "workhorse", temperature: float = 0,
                    **kw) -> tuple[dict, LLMResult]:
    """Structured output: the model is constrained to `schema`; returns (parsed, result).

    Constrained decoding still occasionally yields malformed JSON (seen with both Gemma 4 and gpt-oss),
    and at temperature 0 a retry would repeat it, so the one retry samples at 0.3 or more."""
    for attempt, temp in ((1, temperature), (2, max(temperature, 0.3))):
        res = await chat(messages, alias, json_schema=schema, temperature=temp, **kw)
        text = res.text.strip().removeprefix("```json").removesuffix("```").strip()
        try:
            return json.loads(text), res
        except json.JSONDecodeError as exc:
            if attempt == 2:
                raise JSONOutputError(str(exc), res.text) from exc
    raise AssertionError("unreachable")


async def stream(messages: list[dict], alias: str = "workhorse", max_tokens: int = 1024,
                 temperature: float = 0.2) -> AsyncIterator[str]:
    """Token stream for chat UIs (Server-Sent Events from the gateway)."""
    body = {"model": alias, "messages": messages, "max_tokens": max_tokens, "temperature": temperature, "stream": True}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        async with client.stream("POST", f"{settings.llm_gateway_url}/chat/completions", json=body, headers=_headers()) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                delta = json.loads(line[6:])["choices"][0].get("delta", {}).get("content")
                if delta:
                    yield delta


def image_part(png_base64: str) -> dict:
    """Message content part for the vision alias."""
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png_base64}"}}
