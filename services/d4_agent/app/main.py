"""D4 · AI Virtual Agent (PLAN.md §4 D4).

A customer speaks or types (Arabic, Egyptian dialect or English). The agent authenticates with a mock
OTP, blocks a card, logs a complaint and hands off to a human on request. Guardrails run on every
input and output; a blocked turn shows a live STOP marker. Every banking action hits the mock bank.

Two lessons from the Arabic gate are built in:
- Tool calls are enforced: a reply that promises an action ("I'll send you a code") without calling
  the tool is retried with tool_choice=required.
- The OTP code never reaches the model (it is shown only on the UI's phone mock-up), so it cannot
  leak into a reply.
"""
import base64
import json
import re
import time
import uuid
from pathlib import Path

import httpx
from fastapi import HTTPException
from pydantic import BaseModel

from nbe_core import create_app, llm, platform, retrieval
from nbe_core.audit import log_event
from nbe_core.text import detect_lang
from nbe_core.trace import Trace

KB = Path("/data/seed/d4/kb.json")
COLLECTION = "d4_kb"
ASR_URL, TTS_URL = "http://nbe-asr:8000", "http://nbe-tts:8000"
app = create_app("d4", "AI Virtual Agent", phase="wave2")
SESSIONS: dict[str, dict] = {}

TOOLS = [
    {"name": "send_otp", "description": "Send a one-time password to the customer's registered phone. Required before any card or account action.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "verify_otp", "description": "Verify the OTP code the customer read out or typed.",
     "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}},
    {"name": "get_cards", "description": "List the verified customer's cards (last 4 digits, type, status).", "parameters": {"type": "object", "properties": {}}},
    {"name": "get_balance", "description": "Get the verified customer's account balance.", "parameters": {"type": "object", "properties": {}}},
    {"name": "block_card", "description": "Block one of the verified customer's cards.",
     "parameters": {"type": "object", "properties": {"last4": {"type": "string"}, "reason": {"type": "string", "enum": ["lost", "stolen", "fraud", "customer_request"]}},
                    "required": ["last4", "reason"]}},
    {"name": "create_ticket", "description": "Log a complaint or service ticket for the customer.",
     "parameters": {"type": "object", "properties": {"category": {"type": "string"}, "description": {"type": "string"}}, "required": ["category", "description"]}},
    {"name": "handoff_to_human", "description": "Transfer the conversation to a human agent. Does not require OTP.",
     "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}},
    {"name": "search_kb", "description": "Search the bank's knowledge base about products, fees, limits and procedures.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
]
OPENAI_TOOLS = [{"type": "function", "function": t} for t in TOOLS]

SYSTEM = """You are the virtual assistant of the National Bank of Egypt (demo). Be warm, brief and precise.
Language: reply in the customer's language. For Arabic (including Egyptian dialect), reply in simple Modern Standard Arabic with a friendly Egyptian tone; for English, reply in English. Keep replies under 60 words: they are read aloud.
Rules:
- Any card or account action, or showing the balance, needs OTP verification first: call send_otp, ask the customer for the code, then call verify_otp with the code they give.
- If the customer reports a lost or stolen card, or unknown transactions, act at once: call send_otp in this turn without asking permission, then ask for the code.
- After verify_otp succeeds for a lost card, call get_cards; if there is one card block it, if several ask which one (by last 4 digits).
- When you say you will do something, call the tool in the same turn. Never claim an action happened unless the tool result confirms it.
- Never ask for or repeat a PIN, password or full card number. You never see OTP codes; the customer reads them from their phone.
- If the customer asks for a human, call handoff_to_human immediately.
- Use search_kb for questions about fees, limits, products or procedures, and answer only from what it returns.
Current customer: {name} (id {cid}). Verified: {verified}.
{lang_rule}"""

PROMISE = re.compile(r"(سأرسل|سارسل|هبعت|سأقوم ب|هقوم ب|سأوقف|سأحول|هحولك|سأحولك|جاري (إرسال|ارسال|إيقاف|تحويل)|I('| wi)ll (send|block|transfer|create|log|connect)|let me (send|block|transfer))", re.I)
REFUSAL = {"ar": "عذراً، لا أستطيع المساعدة في هذا الطلب. يمكنني مساعدتك في البطاقات والحسابات والشكاوى، أو تحويلك إلى أحد موظفينا.",
           "en": "Sorry, I can't help with that request. I can help with cards, accounts and complaints, or connect you to one of our agents."}


@app.post("/admin/ingest")
async def ingest():
    arts = json.loads(KB.read_text(encoding="utf-8"))
    await retrieval.ensure_collection(COLLECTION, recreate=True)
    texts = [f"{a['question_ar']}\n{a['answer_ar']}\n{a['question_en']}\n{a['answer_en']}" for a in arts]
    n = await retrieval.upsert(COLLECTION, texts, [{"id": a["id"], "topic": a["topic"]} for a in arts])
    return {"articles": n}


@app.get("/customers")
async def customers():
    return (await platform.mockbank("GET", "/customers"))[:8]


class SessionIn(BaseModel):
    customer_id: str = "C0001"


@app.post("/session")
async def new_session(body: SessionIn):
    custs = {c["id"]: c for c in await platform.mockbank("GET", "/customers")}
    if body.customer_id not in custs:
        raise HTTPException(404, "unknown customer")
    sid = uuid.uuid4().hex[:12]
    c = custs[body.customer_id]
    SESSIONS[sid] = {"customer": c, "messages": [], "token": None, "verified": False, "created": time.time()}
    return {"session_id": sid, "customer": c}


async def run_tool(s: dict, name: str, args: dict, events: list) -> dict:
    cid = s["customer"]["id"]
    tok = s["token"]
    if name == "send_otp":
        r = await platform.mockbank("POST", "/otp/send", {"customer_id": cid})
        events.append({"type": "sms", "to": r.get("to"), "code": r.get("demo_code")})       # phone mock-up only
        return {"sent": r.get("sent", False), "to": r.get("to"), "expires_in_s": r.get("expires_in_s")}   # no code for the model
    if name == "verify_otp":
        r = await platform.mockbank("POST", "/otp/verify", {"customer_id": cid, "code": str(args.get("code", ""))})
        if r.get("verified"):
            s["token"], s["verified"] = r["session"], True
        return {"verified": bool(r.get("verified"))}
    if name == "get_cards":
        return {"cards": await platform.mockbank("GET", "/cards", session=tok)}
    if name == "get_balance":
        return await platform.mockbank("GET", "/balance", session=tok)
    if name == "block_card":
        return await platform.mockbank("POST", f"/cards/{args.get('last4', '')}/block", {"reason": args.get("reason", "lost")}, session=tok)
    if name == "create_ticket":
        return await platform.mockbank("POST", "/tickets", {"customer_id": cid, "category": args.get("category", "general"),
                                                            "description": args.get("description", ""), "channel": "virtual_agent"})
    if name == "handoff_to_human":
        summary = " | ".join(m["content"][:120] for m in s["messages"] if m["role"] == "user")[-500:]
        return await platform.mockbank("POST", "/handoff", {"customer_id": cid, "reason": args.get("reason", "customer_request"), "summary": summary})
    if name == "search_kb":
        hits = await retrieval.search(COLLECTION, args.get("query", ""), k=2, candidates=10)
        return {"results": [h["text"][:700] for h in hits]}
    return {"error": f"unknown tool {name}"}


class TurnIn(BaseModel):
    session_id: str
    text: str | None = None
    audio_b64: str | None = None       # browser recording (webm/opus or wav)
    voice: bool = False                # speak the reply


@app.post("/turn")
async def turn(body: TurnIn):
    s = SESSIONS.get(body.session_id)
    if not s:
        raise HTTPException(404, "session expired; start a new one")
    trace, events = Trace(), []
    text = (body.text or "").strip()
    if body.audio_b64:
        async with httpx.AsyncClient(timeout=120) as c:
            r = (await c.post(f"{ASR_URL}/transcribe", files={"file": ("turn.webm", base64.b64decode(body.audio_b64))}, data={"language": "auto"})).json()
        text = r["text"]
        trace.add("asr", "Speech to text (whisper-large-v3)", r, r.get("latency_ms"))
        events.append({"type": "transcript", "text": text})
    if not text:
        raise HTTPException(400, "empty turn")
    lang = detect_lang(text)

    g = await platform.guard_input(text)
    trace.add("guardrail", "Input guardrail (NeMo self-check)", g, g["latency_ms"])
    if not g["allowed"]:
        events.append({"type": "guardrail", "stage": "input", "rail": g["rail"]})
        reply = REFUSAL[lang]
        s["messages"] += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        await log_event("guardrail", "input", {"session": body.session_id, "rail": g["rail"]})
        return await finish(s, body, reply, events, trace, blocked=True)

    s["messages"].append({"role": "user", "content": text})
    lang_rule = ("The customer's latest message is in Arabic: reply in Arabic." if lang == "ar" else
                 "The customer's latest message is in English: reply in English only.")
    system = SYSTEM.format(name=s["customer"]["name_ar"] if lang == "ar" else s["customer"]["name_en"], cid=s["customer"]["id"],
                           verified=s["verified"], lang_rule=lang_rule)
    tools_called = 0
    reply = ""
    for step in range(6):
        res = await llm.chat([{"role": "system", "content": system}, *s["messages"]], tools=OPENAI_TOOLS, max_tokens=400, temperature=0.2)
        trace.llm(f"Agent step {step + 1} (workhorse)", res)
        if not res.tool_calls and PROMISE.search(res.text or "") and tools_called == 0:
            # Promised an action without doing it (the Arabic gate's egy-02 failure): retry with a tool call required
            trace.add("rules", "Promise without a tool call: retrying with tool_choice=required", res.text)
            res = await llm.chat([{"role": "system", "content": system}, *s["messages"]], tools=OPENAI_TOOLS, max_tokens=400,
                                 temperature=0.2, tool_choice="required")
            trace.llm("Agent step (tool call required)", res)
        if not res.tool_calls:
            reply = (res.text or "").strip()
            break
        s["messages"].append({"role": "assistant", "content": res.text or "", "tool_calls": res.tool_calls})
        for call in res.tool_calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            t = time.time()
            result = await run_tool(s, name, args, events)
            ms = int((time.time() - t) * 1000)
            tools_called += 1
            events.append({"type": "tool", "name": name, "args": args, "result": result, "ms": ms})
            trace.add("tool", f"{name}({', '.join(f'{k}={v}' for k, v in args.items())})", result, ms)
            s["messages"].append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False, default=str)})
            await log_event("tool_call", name, {"session": body.session_id, "args": args})
            if name == "verify_otp":
                system = SYSTEM.format(name=s["customer"]["name_ar"] if lang == "ar" else s["customer"]["name_en"],
                                       cid=s["customer"]["id"], verified=s["verified"], lang_rule=lang_rule)
    if not reply:
        reply = "تم." if lang == "ar" else "Done."

    g = await platform.guard_output(reply, user=text)
    trace.add("guardrail", "Output guardrail (NeMo self-check)", g, g["latency_ms"])
    blocked = not g["allowed"]
    if blocked:
        events.append({"type": "guardrail", "stage": "output", "rail": g["rail"]})
        reply = REFUSAL[lang]
    s["messages"].append({"role": "assistant", "content": reply})
    return await finish(s, body, reply, events, trace, blocked=blocked)


async def finish(s: dict, body: TurnIn, reply: str, events: list, trace: Trace, blocked: bool) -> dict:
    audio = None
    if body.voice:
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(f"{TTS_URL}/tts", json={"text": re.sub(r"[*#_`]", "", reply), "lang": detect_lang(reply)})
            audio = base64.b64encode(r.content).decode()
            trace.add("tts", "Text to speech (Piper)", None, int(r.headers.get("X-Latency-Ms", 0)))
        except httpx.HTTPError:
            trace.add("tts", "Text to speech unavailable (voice profile off)")
    return {"reply": reply, "blocked": blocked, "events": events, "audio_wav_b64": audio, "verified": s["verified"],
            "trace": trace.to_list(), "total_ms": trace.total_ms()}


@app.get("/state/{sid}")
async def state(sid: str):
    s = SESSIONS.get(sid)
    if not s:
        raise HTTPException(404, "unknown session")
    cards = await platform.mockbank("GET", "/cards", session=s["token"]) if s["token"] else None
    return {"customer": s["customer"], "verified": s["verified"], "cards": cards,
            "tickets": [t for t in await platform.mockbank("GET", "/tickets") if t["customer_id"] == s["customer"]["id"]][:5],
            "handoffs": [h for h in await platform.mockbank("GET", "/handoffs") if h["customer_id"] == s["customer"]["id"]][:5]}


@app.post("/admin/reset")
async def reset():
    SESSIONS.clear()
    return await platform.mockbank("POST", "/admin/reset")
