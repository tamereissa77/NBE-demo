"""D6 · NBE AI Assistant (PLAN.md §4 D6).

One assistant for file chat, drafting, summarisation, translation and code explanation. A router picks
the model per task and says why; the portal shows that as the Model-Selection Panel.

Two front doors:
  /chat, /upload, /route      portal (behind the gateway at /api/d6)
  /v1/chat/completions, /v1/models   OpenAI-compatible, model "nbe-auto", for Open WebUI and Dataiku LLM Mesh
                                      (gateway path /v1; bearer key D6_API_KEY when set)
"""
import json
import os
import re
import time
import uuid
from pathlib import Path

import httpx
from fastapi import File, Header, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from nbe_core import create_app, llm, platform, retrieval, settings
from nbe_core.text import detect_lang
from nbe_core.trace import Trace

DOCS_DIR = Path("/data/generated/d6")
COLLECTION = "d6_docs"
API_KEY = os.getenv("D6_API_KEY", "")
app = create_app("d6", "NBE AI Assistant", phase="wave1")
FILES: dict[str, dict] = {}       # uploaded files for file chat (in memory, demo scope)

# Task -> model alias, and why. "hero" falls back to the workhorse at the gateway when it is not running.
ROUTES = {
    "file_chat": ("workhorse", "File chat and extraction: long context, Arabic, fast"),
    "drafting": ("workhorse", "Drafting emails and letters: fluent Arabic and English"),
    "summarise": ("workhorse", "Summaries and key points: fast, good Arabic"),
    "translation": ("workhorse", "Translation Arabic ↔ English: strongest Arabic among fast models"),
    "code": ("hero", "Code explanation: gpt-oss-120b reasons best about code; answers grounded in local docs"),
    "general": ("workhorse", "General questions: the fast default"),
}
RULES = [  # cheap first pass; the LLM classifier handles anything the rules do not catch
    ("code", r"```|\bdef |\bclass |\bimport |\bSELECT\b|\bpandas\b|\bnumpy\b|\bpython\b|\bSQL\b|\bdf\.|\.groupby\(|كود|برمج|دالة|الكود"),
    ("translation", r"\btranslat|ترجم|ترجمة|للإنجليزي|للانجليزي|للعربي|بالإنجليزية|into english|into arabic"),
    ("summarise", r"\bsummar|لخص|لخّص|تلخيص|key points|النقاط الرئيسية|أهم النقاط"),
    ("drafting", r"\bdraft|\bwrite an? (email|letter)|اكتب(لي)? (إيميل|ايميل|بريد|خطاب|رسالة)|صياغة|صيغ"),
]


def require_key(authorization: str | None) -> None:
    if API_KEY and authorization != f"Bearer {API_KEY}":
        raise HTTPException(401, "invalid API key")


async def route(text: str, has_file: bool) -> dict:
    """Language + task + model, with the reason. Rules first, then a small LLM classification."""
    lang = detect_lang(text)
    if has_file and not re.search(RULES[1][1], text, re.I):
        task, how = "file_chat", "rule: a file is attached"
    else:
        task, how = None, ""
        for name, pattern in RULES:
            if re.search(pattern, text, re.I):
                task, how = name, f"rule: matched {name} keywords"
                break
        if task is None:
            data, _ = await llm.chat_json([{"role": "user", "content":
                "Classify the employee's request into one task: file_chat, drafting, summarise, translation, code, general. "
                f"Answer JSON only.\nRequest: {text[:1500]}"}],
                {"type": "object", "properties": {"task": {"type": "string", "enum": list(ROUTES)}}, "required": ["task"]}, max_tokens=20)
            task, how = data["task"], "LLM classifier (workhorse)"
    alias, reason = ROUTES[task]
    return {"lang": lang, "task": task, "alias": alias, "reason": reason, "how": how}


async def code_context(question: str, trace: Trace) -> str:
    with trace.step("retrieval", "Ground code answer in local pandas/numpy docs") as s:
        try:
            hits = await retrieval.search(COLLECTION, question, k=3, candidates=12)
        except httpx.HTTPError:
            hits = []
        s["detail"] = [h.get("name") for h in hits]
    if not hits:
        return ""
    return "Reference documentation (use only APIs documented here or in the standard library):\n" + \
        "\n\n".join(f"### {h['name']}\n{h['text'][:1800]}" for h in hits)


SYSTEM = {
    "ar": ("أنت مساعد موظفي البنك الأهلي المصري. أجب بالعربية الفصحى الواضحة ما لم يُطلب غير ذلك. كن دقيقاً ومختصراً، "
           "ولا تخترع معلومات عن البنك. عند شرح الأكواد اكتب المصطلحات التقنية بالإنجليزية."),
    "en": "You are National Bank of Egypt's internal employee assistant. Be accurate and concise; never invent bank facts.",
}


# Per-task output rules. The Arabic gate showed the models add preambles and several alternatives to drafts.
TASK_RULES = {
    "drafting": "Write exactly one version, ready to send. No preamble, no alternatives, no notes after it.",
    "translation": "Output only the translation, with no quotes, labels or commentary.",
    "summarise": "Output only the summary in the requested form.",
    "code": "Explain clearly, point out real bugs, and only use APIs that exist in the documented library versions.",
}


def build_messages(messages: list[dict], r: dict, extra_context: str = "") -> list[dict]:
    sys = SYSTEM[r["lang"]] + (" " + TASK_RULES[r["task"]] if r["task"] in TASK_RULES else "") + \
        ("\n\n" + extra_context if extra_context else "")
    return [{"role": "system", "content": sys}, *[m for m in messages if m["role"] != "system"]]


class ChatIn(BaseModel):
    messages: list[dict]
    file_id: str | None = None


@app.post("/chat")
async def chat(body: ChatIn):
    trace = Trace()
    question = body.messages[-1]["content"]
    f = FILES.get(body.file_id) if body.file_id else None
    with trace.step("route", "Detect language and task, choose model") as s:
        r = await route(question, f is not None)
        s["detail"] = r
    extra = ""
    if r["task"] == "code":
        extra = await code_context(question, trace)
    if f:
        extra = (f"Attached file: {f['name']}\n---\n{f['text'][:24000]}\n---\n"
                 "Answer from the file when the question is about it, and say where in the file the answer is.")
    kwargs = {"reasoning_effort": "low"} if r["alias"] == "hero" else {}
    res = await llm.chat(build_messages(body.messages, r, extra), r["alias"], max_tokens=1500, temperature=0.2, **kwargs)
    trace.llm(f"Answer ({r['alias']})", res)
    r["model"], r["fallback"] = res.model, res.model != r["alias"]
    return {"answer": res.text, "route": r, "meta": res.meta(), "trace": trace.to_list()}


@app.post("/route")
async def route_only(body: ChatIn):
    return await route(body.messages[-1]["content"], bool(body.file_id))


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    data = await file.read()
    conv = await platform.convert_document(file.filename or "file", data)
    text, how = conv["markdown"], "Docling"
    if conv.get("rtl_pdf"):
        pages = await platform.render_pdf(data)
        parts = []
        for p in pages[:15]:
            res = await llm.chat([{"role": "user", "content": [llm.image_part(p), {"type": "text", "text": "انسخ نص الصفحة إلى Markdown كما هو. النص فقط."}]}],
                                 "vision", max_tokens=1800, temperature=0)
            parts.append(res.text)
        text, how = "\n\n".join(parts), f"vision model ({len(pages)} page(s); Arabic PDF)"
    fid = uuid.uuid4().hex[:10]
    FILES[fid] = {"name": file.filename, "text": text}
    return {"file_id": fid, "name": file.filename, "chars": len(text), "pages": conv.get("pages"), "converted_by": how,
            "preview": text[:600]}


@app.post("/admin/ingest")
async def ingest():
    docs = [json.loads(line) for line in (DOCS_DIR / "docs.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    await retrieval.ensure_collection(COLLECTION, recreate=True)
    n = await retrieval.upsert(COLLECTION, [d["text"] for d in docs], [{"name": d["name"], "library": d["library"]} for d in docs])
    return {"ingested": n}


# ------------------------------------------------------------------ OpenAI-compatible endpoint (Open WebUI, Dataiku LLM Mesh)
@app.get("/v1/models")
def models(authorization: str | None = Header(default=None)):
    require_key(authorization)
    now = int(time.time())
    return {"object": "list", "data": [{"id": m, "object": "model", "created": now, "owned_by": "nbe-gb10"}
                                       for m in ("nbe-auto", "workhorse", "hero")]}


@app.post("/v1/chat/completions")
async def completions(request: Request, authorization: str | None = Header(default=None)):
    require_key(authorization)
    body = await request.json()
    messages = body.get("messages", [])
    last = messages[-1]["content"] if messages else ""
    if isinstance(last, list):   # content parts
        last = " ".join(p.get("text", "") for p in last if p.get("type") == "text")
    if body.get("model", "nbe-auto") == "nbe-auto":
        r = await route(last, False)
    else:
        alias = body["model"] if body["model"] in ("workhorse", "hero") else "workhorse"
        r = {"lang": detect_lang(last), "task": "explicit", "alias": alias, "reason": "model requested explicitly", "how": "client"}
    extra = await code_context(last, Trace()) if r["task"] == "code" else ""
    upstream = {**body, "model": r["alias"], "messages": build_messages(messages, r, extra)}
    if r["alias"] == "hero":
        upstream.setdefault("reasoning_effort", "low")
    headers = {"Authorization": f"Bearer {settings.llm_gateway_key}"}
    route_headers = {"X-NBE-Route-Task": r["task"], "X-NBE-Route-Model": r["alias"], "X-NBE-Route-Lang": r["lang"]}
    url = f"{settings.llm_gateway_url}/chat/completions"
    if body.get("stream"):
        async def relay():
            async with httpx.AsyncClient(timeout=600) as client:
                async with client.stream("POST", url, json=upstream, headers=headers) as resp:
                    async for chunk in resp.aiter_raw():
                        yield chunk
        return StreamingResponse(relay(), media_type="text/event-stream", headers=route_headers)
    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(url, json=upstream, headers=headers)
    data = resp.json()
    data["nbe_route"] = r
    from fastapi.responses import JSONResponse
    return JSONResponse(data, status_code=resp.status_code, headers=route_headers)


@app.get("/suggested")
def suggested():
    return [
        {"task": "drafting", "q": "اكتب بريداً رسمياً لمديري الفروع عن صيانة نظام الحوالات يوم الجمعة من 1 إلى 5 صباحاً"},
        {"task": "translation", "q": "ترجم للإنجليزية: يُعفى عملاء حسابات الرواتب من رسوم استبدال البطاقات المفقودة."},
        {"task": "summarise", "q": "لخّص في ثلاث نقاط: تأجيل تحديث نظام البطاقات من 16 إلى 23 أكتوبر بسبب تأخر المورد، ويمكن إصدار بطاقات الخصم فقط أثناء التحديث."},
        {"task": "code", "q": "Explain this and fix any bug:\n```python\ndf.groupby('branch')['amount'].agg('sum').sort_values(ascending=False).head(5)\n```"},
        {"task": "code", "q": "اشرحلي الكود ده:\n```python\nimport pandas as pd\ndf = pd.read_csv('txns.csv', parse_dates=['ts'])\nmonthly = df.resample('M', on='ts')['amount'].sum()\n```"},
    ]
