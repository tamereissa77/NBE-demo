"""D4 · AI Virtual Agent (PLAN.md §4 D4).

A customer speaks or types (Arabic, Egyptian dialect or English). The agent authenticates with a mock
OTP, blocks a card, logs a complaint and hands off to a human on request. Guardrails run on every
input and output; a blocked turn shows a live STOP marker. Every banking action hits the mock bank.

Built in, from the Arabic gate and from testing:
- Tool calls are enforced: a reply that promises an action ("I'll send you a code") without calling
  the tool is retried with tool_choice=required.
- The one-time code bypasses the models. It is shown only on the UI's phone mock-up; what the customer
  enters (keypad, chat or voice) goes straight to the bank, and the agent is told only the verdict.
- A card is blocked only after the customer has been asked about that card and answered.
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
from nbe_core.text import arabic_ratio, detect_lang
from nbe_core.trace import Trace
from app import speech

KB = Path("/data/seed/d4/kb.json")
COLLECTION = "d4_kb"
ASR_URL, TTS_URL = "http://nbe-asr:8000", "http://nbe-tts:8000"
app = create_app("d4", "AI Virtual Agent", phase="wave2")
SESSIONS: dict[str, dict] = {}

TOOLS = [
    {"name": "send_otp", "description": "Send a one-time code to the customer's registered phone. Required before any card or account action. "
                                         "The customer then enters it; the bank checks it and you are told only the result.",
     "parameters": {"type": "object", "properties": {}}},
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
Language: reply in the customer's language. For Arabic, always reply in Egyptian colloquial Arabic (عامية مصرية), the way a warm, respectful call-centre agent in Cairo speaks, even when the customer or the knowledge base uses formal Arabic. Say «حضرتك», «يا فندم», «عايز», «دلوقتي», «هبعتلك», «ممكن تقولي», «ولا يهمك», «عشان». Start each reply with the answer itself: do not open with an acknowledgement such as «تمام يا فندم», «حاضر يا فندم» or «بص يا فندم», and use «يا فندم» at most once in a reply, not in every reply. Never use formal wording such as «أهلاً بك», «سأقوم», «لقد», «يرجى», «الذي», «لدينا», «هل تريد», «سوف», «يمكنني», «نتحقق» (say «نتأكد»). For English, reply in English. Keep replies under 60 words: they are read aloud.
Rules:
- Any card or account action, or showing the balance, needs OTP verification first: call send_otp, then tell the customer you sent a code to their phone and ask them to enter it. The bank checks the code itself and a system note then tells you whether it was accepted; you have no tool to verify a code, and any digits the customer sends meanwhile reach you masked as ••••, which is normal.
- If the customer reports a lost or stolen card, or unknown transactions, act at once: call send_otp in this turn without asking permission, then ask them to enter the code.
- Once the customer is verified for a lost card, call get_cards, then ask the customer to confirm the card to block by its last 4 digits. Blocking cannot be undone here: call block_card only after the customer has confirmed that card in their reply.
- When you say you will do something, call the tool in the same turn. Never claim an action happened unless the tool result confirms it.
- Never ask for or repeat a PIN, password or full card number.
- If the customer asks for a human, call handoff_to_human immediately.
- Use search_kb for questions about fees, limits, products or procedures, and answer only from what it returns.
- Small talk about yourself is not banking: no tool, no knowledge-base search. You are the bank's automated assistant; never say you are a person. Reply with exactly the line below that fits, in the customer's language, and nothing before or after it (no greeting, no introduction, no offer of help):
  - A compliment on your voice, your looks or yourself («صوتك حلو», «انتي جميلة», «شكلك مزة», «بحب صوتك», "you sound lovely", "I love your voice"): «ميرسي، شكراً ليك.» / "Thank you, that's kind of you."
  - Your age: «أنا مساعد آلي، معنديش سنين زي البشر.» / "I'm an automated assistant, I don't have an age the way people do."
  - Where you are from or where you live: «أنا مساعد آلي للبنك الأهلي المصري وموجودة في كل فروع البنك، اتفضل زورنا في أقرب فرع ليك.» / "I'm the National Bank of Egypt's automated assistant and I'm in every branch. You're welcome to visit the one nearest you."
  - Your name, or whether you are a person or a robot: «أنا المساعد الآلي للبنك الأهلي المصري، مش إنسان.» / "I'm the National Bank of Egypt's automated assistant, not a person."
  - Anything else about you (married, tired, what you like): «أنا مساعد آلي للبنك الأهلي المصري، وموجودة عشان أساعدك.» / "I'm the National Bank of Egypt's automated assistant, here to help you."
  If the same message also asks a banking question, answer the banking question after the line.
Current customer: {name} (id {cid}). Verified: {verified}.
{lang_rule}"""

PROMISE = re.compile(r"(سأرسل|سارسل|هبعت|هشوف|هوقف|هقفل|هسجل|هحول|هعمل(ك|لك)? (شكوى|بلاغ|تذكرة)|هفتح(لك)? (شكوى|بلاغ|تذكرة)|سأقوم (الآن )?ب|هقوم (دلوقتي )?ب|سأوقف|سأحول|هحولك|سأحولك|جاري (إرسال|ارسال|إيقاف|تحويل)|I('| wi)ll (send|block|transfer|create|log|connect)|let me (send|block|transfer))", re.I)
ACTIONS = {"send_otp", "block_card", "create_ticket", "handoff_to_human"}
# A greeting that opens a reply, one or two in a row ("أهلاً يا محمد، ازيك يا فندم؟"). A returned «وعليكم السلام» is kept.
GREETING = re.compile(r"^\s*(وعليكم السلام[^،,.؟?!\n]{0,30}[،,.؟?!]\s*)?"
                      r"(?:(?:[اإ]زيك|[أا]هلا|أهلاً|اهلاً|مرحبا|مرحباً|hi|hello|hey)\b[^،,.؟?!\n]{0,40}[،,.؟?!]\s*){1,2}", re.I)
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
# An acknowledgement that opens a reply and adds nothing: «تمام يا فندم، ...». Heard at the start of every reply.
FILLER = re.compile(r"^\s*(?:تمام|حاضر|ماشي|طيب|بص)(?:\s+يا\s+فندم)?\s*[،,.!:]+\s*(?=\S)")
LEAKED_CALL = re.compile(r"\s*(call:\w+\s*\{|<\|?tool_call)")      # Gemma's raw tool-call syntax
PLAN_NOTES = re.compile(r"\s*(\d+\.\s*)?\*\*[^*]{2,40}\*\*")           # "1.  **Customer Name:** ...": the model's working notes


def off_script(reply: str, lang: str) -> bool:
    """Not something to say to the customer: a tool call returned as text, the model's planning notes, or an
    answer in English to a customer who wrote Arabic. All three were seen from the hosted model."""
    return bool(LEAKED_CALL.match(reply) or PLAN_NOTES.match(reply) or (lang == "ar" and reply and arabic_ratio(reply[:80]) < 0.3))
# The bank's codes are 4 digits; a voice transcript spaces them out ("4 1 7 9"). Five digits is not a code.
OTP_CODE = re.compile(r"(?<!\d)(?<!\d\s)(?<!\d-)\d(?:[\s-]?\d){3}(?![\s-]?\d)")
OTP_NOTE = {True: "[System note, not typed by the customer: the customer entered the one-time code and the bank confirmed it. "
                  "They are verified now. Continue with what they asked for.]",
            False: "[System note, not typed by the customer: the customer entered a one-time code and the bank rejected it: wrong or expired. "
                   "Say so and offer to send a new code.]"}
# Said when the model still has no words: the customer must at least be asked for the code that was sent
ASK_CODE = {"ar": "بعتلك كود في رسالة على موبايلك، ممكن تدخل الكود اللي وصلك؟", "en": "I've sent a code to your phone. Please enter it to continue."}
DONE = {"ar": "تمام.", "en": "Done."}
# Said when a voice recording could not be made out (the speech service reports it as not heard)
UNCLEAR = {"ar": "مسمعتش كويس، الصوت مش واضح. ممكن تكرر سؤالك أو تكتبه؟",
           "en": "Sorry, I didn't catch that: the sound wasn't clear. Could you say it again, or type it?"}
REFUSAL = {"ar": "معلش، مش هقدر أساعد حضرتك في الطلب ده. أقدر أساعدك في البطاقات والحسابات والشكاوى، أو أحوّلك لحد من زمايلنا.",
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
        s["otp_pending"] = bool(r.get("sent"))
        return {"sent": r.get("sent", False), "to": r.get("to"), "expires_in_s": r.get("expires_in_s")}   # no code for the model
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
        # Arabic question and answer come first in an article and run to about 900 characters: a shorter
        # cut dropped the end of the longer answers
        return {"results": [h["text"][:1000] for h in hits]}
    return {"error": f"unknown tool {name}"}


async def check_code(sid: str, s: dict, keypad: str | None, text: str, events: list, trace: Trace) -> tuple[str, str]:
    """The one-time code goes from the keypad, the chat or the voice transcript straight to the bank.
    Returns the customer's message with every digit masked, which is all that the models get (the agent and
    the guardrail, a model too), and a note for the agent saying only whether the bank accepted the code."""
    digits = text.translate(AR_DIGITS)
    found = OTP_CODE.search(digits)
    code = re.sub(r"\D", "", keypad or (found.group(0) if found else ""))
    masked = re.sub(r"\d", "•", digits)
    if not code:
        return masked, ""
    t = time.time()
    r = await platform.mockbank("POST", "/otp/verify", {"customer_id": s["customer"]["id"], "code": code})
    ok = bool(r.get("verified"))
    if ok:
        s["token"], s["verified"], s["otp_pending"] = r["session"], True, False
    ms = int((time.time() - t) * 1000)
    events.append({"type": "otp", "verified": ok, "via": "keypad" if keypad else "message", "ms": ms})
    trace.add("rules", "One-time code checked by the bank directly: no model sees it", {"verified": ok}, ms)
    await log_event("otp_check", "bank", {"session": sid, "verified": ok})
    return masked, OTP_NOTE[ok] + (" Reply in Egyptian colloquial Arabic." if s.get("lang") == "ar" else " Reply in English.")


class TurnIn(BaseModel):
    session_id: str
    text: str | None = None
    audio_b64: str | None = None       # browser recording (webm/opus or wav)
    code: str | None = None            # one-time code typed on the keypad: goes to the bank, never to a model
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
        trace.add("asr", f"Speech to text ({r.get('model', 'whisper-large-v3')})", r, r.get("latency_ms"))
        if not text or not r.get("heard", True):
            # Silence, noise or a mumble: the recogniser still writes a sentence, one nobody said. It is not
            # shown as the customer's words and no model or tool sees it; the customer is asked to repeat.
            trace.add("rules", "Recording not heard clearly: asked the customer to repeat or type; nothing reached the agent")
            return await finish(s, body, UNCLEAR[s.get("lang", "ar")], events, trace, blocked=False)
        events.append({"type": "transcript", "text": text})
    if not text and not body.code:
        raise HTTPException(400, "empty turn")
    lang = s["lang"] = detect_lang(text) if text else s.get("lang", "ar")     # a keypad entry has no words: keep the conversation's language
    note = ""
    if body.code or s.get("otp_pending"):
        text, note = await check_code(body.session_id, s, body.code, text, events, trace)

    if text:                      # nothing the customer wrote reaches a model on a keypad entry
        g = await platform.guard_input(text)
        trace.add("guardrail", "Input guardrail (NeMo self-check)", g, g["latency_ms"])
        if not g["allowed"]:
            events.append({"type": "guardrail", "stage": "input", "rail": g["rail"]})
            reply = REFUSAL[lang]
            s["messages"] += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
            await log_event("guardrail", "input", {"session": body.session_id, "rail": g["rail"]})
            return await finish(s, body, reply, events, trace, blocked=True)
    text = "\n".join(part for part in (text, note) if part)

    # The reply the customer is answering now. A card is blocked only if that reply named it, so the
    # customer has seen which card and answered: confirm-before-block is enforced here, not left to the prompt.
    asked = next((m["content"] for m in reversed(s["messages"]) if m["role"] == "assistant" and not m.get("tool_calls")), "").translate(AR_DIGITS)
    s["messages"].append({"role": "user", "content": text})
    lang_rule = ("The customer's latest message is in Arabic: reply in Egyptian colloquial Arabic, not formal Arabic." if lang == "ar" else
                 "The customer's latest message is in English: reply in English only.")
    first = len(s["messages"]) == 1
    if first:                        # the model skips the greeting once a tool has run unless told it is the first reply
        lang_rule += (" This is your first reply in this conversation: after any tool call, begin the reply by greeting the customer by first name"
                      + (" with «ازيك يا» and their first name (say «وعليكم السلام» before it if they said السلام عليكم)" if lang == "ar" else "")
                      + " and add a few kind words about their problem, then continue.")
    else:
        lang_rule += " You have already greeted the customer: do not greet again (no «ازيك», «أهلاً», hi or hello), go straight to the answer."
    system = SYSTEM.format(name=s["customer"]["name_ar"] if lang == "ar" else s["customer"]["name_en"], cid=s["customer"]["id"],
                           verified=s["verified"], lang_rule=lang_rule)
    acted = False             # an action tool ran this turn (lookups such as get_cards do not count)
    said = ""                 # what the model wrote in the same message as a tool call
    reply = ""
    for step in range(6):
        # Once a code has been sent there is nothing to do but ask for it: the model gets no tools for that reply.
        # Offered tools, it tried a second call (search_kb, handoff) that came back empty or as raw text.
        tools = None if s.get("otp_pending") and acted else OPENAI_TOOLS
        res = await llm.chat([{"role": "system", "content": system}, *s["messages"]], tools=tools, max_tokens=400, temperature=0.2)
        trace.llm(f"Agent step {step + 1} (workhorse)", res)
        if not res.tool_calls and PROMISE.search(res.text or "") and not acted:
            # Promised an action without doing it (the Arabic gate's egy-02 failure): retry with a tool call required.
            # Once only, and not after an action already ran: a forced call must never repeat one.
            acted = True
            trace.add("rules", "Promise without a tool call: retrying with tool_choice=required", res.text)
            res = await llm.chat([{"role": "system", "content": system}, *s["messages"]], tools=OPENAI_TOOLS, max_tokens=400,
                                 temperature=0.2, tool_choice="required")
            trace.llm("Agent step (tool call required)", res)
        if not res.tool_calls:
            reply = (res.text or "").strip()
            if off_script(reply, lang):           # never shown, and a tool call in it is never run
                trace.add("rules", "Not a reply to the customer (raw tool call, planning notes or wrong language): discarded", reply)
                reply = ""
            break
        s["messages"].append({"role": "assistant", "content": res.text or "", "tool_calls": res.tool_calls})
        said = (res.text or "").strip() or said
        for call in res.tool_calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            t = time.time()
            if name == "block_card" and args.get("last4") and str(args["last4"]) not in asked:
                result = {"blocked": False, "confirmation_required": True,
                          "instruction": f"Not blocked yet. Ask the customer to confirm blocking the card ending {args['last4']}; block it only after they agree."}
            else:
                result = await run_tool(s, name, args, events)
            ms = int((time.time() - t) * 1000)
            if "error" in result or result.get("confirmation_required"):
                said = ""         # written before the tool answered, and the tool did not do what it announces
            acted = acted or name in ACTIONS
            events.append({"type": "tool", "name": name, "args": args, "result": result, "ms": ms})
            trace.add("tool", f"{name}({', '.join(f'{k}={v}' for k, v in args.items())})", result, ms)
            s["messages"].append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False, default=str)})
            await log_event("tool_call", name, {"session": body.session_id, "args": args})
    if not reply and said and not off_script(said, lang):
        # The model often speaks and acts in one message, then has nothing to add once the tool has answered
        trace.add("rules", "Reply taken from the message that carried the tool call")
        reply = said
    if not reply:
        # Still no words after a tool result: ask once more, with no tools to call
        res = await llm.chat([{"role": "system", "content": system}, *s["messages"]], max_tokens=400, temperature=0.2)
        trace.llm("Agent reply (empty answer: asked again without tools)", res)
        reply = (res.text or "").strip()
        if not reply or off_script(reply, lang):
            reply = (ASK_CODE if s.get("otp_pending") else DONE)[lang]

    reply = speech.reword(reply)          # words the bank does not want said, replaced before anything shows or speaks them
    if first:                             # the Egyptian greeting, where the model reached for the formal one
        reply = re.sub(r"^(\s*(?:وعليكم السلام[^،,.؟?!\n]{0,30}[،,.؟?!]\s*)?)(?:أهلاً|أهلا|اهلا|مرحباً|مرحبا)(?: بيك| بك| بحضرتك)? يا ", r"\1ازيك يا ", reply)
    else:                                 # one greeting per conversation: the model repeats it however it is told
        reply = GREETING.sub(lambda m: m.group(1) or "", reply, count=1)
        reply = reply[:1].upper() + reply[1:]
    reply = FILLER.sub("", reply, count=1)       # straight to the answer; a reply that is only «تمام يا فندم.» is kept
    reply = reply.replace("**", "")       # the chat shows plain text: Markdown bold would appear as asterisks
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
            audio, model, ms = await say(reply)
            trace.add("tts", f"Text to speech ({model})", None, ms)
        except httpx.HTTPError:
            trace.add("tts", "Text to speech unavailable (voice profile off)")
    return {"reply": reply, "blocked": blocked, "events": events, "audio_wav_b64": audio, "verified": s["verified"],
            "trace": trace.to_list(), "total_ms": trace.total_ms()}


async def say(text: str) -> tuple[str, str, int]:
    """(base64 WAV, model, latency ms) for `text`, rewritten for the voice first (app/speech.py)."""
    lang = detect_lang(text)
    spoken = speech.normalize(text, lang)
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{TTS_URL}/tts", json={"text": spoken, "lang": lang, "lexicon": speech.lexicon() if lang == "ar" else {},
                                                 "careful": speech.careful(spoken)})
        r.raise_for_status()
    return base64.b64encode(r.content).decode(), r.headers.get("X-Model", "Piper"), int(r.headers.get("X-Latency-Ms", 0))


class SpeakIn(BaseModel):
    text: str


@app.post("/speak")
async def speak(body: SpeakIn):
    """Pronounce one chat message: the listen button on every bubble."""
    text = body.text.strip()[:600]
    if not text:
        raise HTTPException(400, "nothing to say")
    try:
        audio, model, ms = await say(text)
    except httpx.HTTPError:
        raise HTTPException(503, "voice is off (start the voice services)") from None
    return {"audio_wav_b64": audio, "model": model, "latency_ms": ms}


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
