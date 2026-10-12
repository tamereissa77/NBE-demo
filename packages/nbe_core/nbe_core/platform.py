"""Clients for the shared platform services: guardrails, mock bank, Docling."""
import httpx

from nbe_core.settings import settings

_TIMEOUT = httpx.Timeout(300, connect=5)


async def guard_input(text: str, config: str = "banking") -> dict:
    """{allowed, rail, message, latency_ms}; allowed=False drives the UI's STOP marker."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(f"{settings.guardrails_url}/check/input", json={"config": config, "text": text})
        r.raise_for_status()
        return r.json()


async def guard_output(text: str, user: str = "", config: str = "banking") -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(f"{settings.guardrails_url}/check/output", json={"config": config, "text": text, "user": user})
        r.raise_for_status()
        return r.json()


async def mockbank(method: str, path: str, json: dict | None = None, session: str | None = None) -> dict:
    """Call the mock bank. Errors come back as {"error": status, "detail": ...} so agents can reason about them."""
    headers = {"X-Session": session} if session else {}
    async with httpx.AsyncClient(timeout=_TIMEOUT, base_url=settings.mockbank_url) as client:
        r = await client.request(method, path, json=json, headers=headers)
        if r.status_code >= 400:
            return {"error": r.status_code, "detail": r.json().get("detail", r.text)}
        return r.json()


async def convert_document(filename: str, data: bytes) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(f"{settings.docling_url}/convert", files={"file": (filename, data)})
        r.raise_for_status()
        return r.json()


async def render_pdf(data: bytes, dpi: int = 150, pages: list[int] | None = None) -> list[str]:
    """PDF pages as base64 PNGs, for vision-LLM transcription of Arabic and scanned pages. `pages` (1-based) limits it."""
    form = {"dpi": str(dpi), "pages": ",".join(map(str, pages or []))}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(f"{settings.docling_url}/render", files={"file": ("doc.pdf", data)}, data=form)
        r.raise_for_status()
        return r.json()["pages"]
