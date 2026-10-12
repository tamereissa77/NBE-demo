"""D4 safety rules, checked with a scripted model and a scripted bank: no model server, database or
network is needed, so this runs anywhere the D4 image does.
    docker run --rm -v ./tests:/tests:ro -v ./data:/data:ro nbe-d4 python /tests/d4_rules.py

Rules under test (services/d4_agent/app/main.py):
- Confirm before block: block_card reaches the bank only if the agent's previous reply named that card,
  so the customer has seen which card and answered.
- The one-time code bypasses the models: from the keypad, the chat or a voice transcript it goes to the
  bank; the agent and the guardrail get the message with its digits masked and only the bank's verdict.
- Speech: amounts are spelled the Egyptian way, identifiers are read digit by digit, banking terms and
  unwanted words follow data/seed/d4/pronunciation.ini.
- Promises are kept: a reply that says it will do something without a tool call is retried with a tool
  call required, once, and never after an action already ran in that turn.
- A recording the speech service did not hear clearly is not treated as the customer's words: no model
  sees it and the customer is asked to repeat or type.
"""
import asyncio
import json
import sys

sys.path.insert(0, ".")        # the service's working directory (/srv in the image) holds `app`
from nbe_core.llm import LLMResult
from app import main as d4

results: list[tuple[bool, str]] = []
bank_calls: list[tuple[str, str]] = []
script: list = []
forced: list[bool] = []          # per model call: was a tool call required?
seen: list[str] = []             # everything any model was sent: agent prompts and guardrail inputs


def check(ok: bool, label: str) -> None:
    results.append((ok, label))
    print(f"  {'PASS' if ok else 'FAIL'} {label}", flush=True)


def call(name: str, **args) -> dict:
    return {"id": f"call_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


async def fake_chat(messages, alias="workhorse", **kw):
    step = script.pop(0)          # words, tool calls, or (words, tool calls) in one message
    forced.append(kw.get("tool_choice") == "required")
    seen.append(json.dumps([messages, kw.get("tools")], ensure_ascii=False))
    text, calls = step if isinstance(step, tuple) else (step, []) if isinstance(step, str) else ("", step)
    return LLMResult(text=text, alias=alias, model=alias, latency_ms=1, tool_calls=calls)


async def fake_bank(method, path, json=None, session=None):
    bank_calls.append((method, path))
    if path == "/otp/send":
        return {"sent": True, "to": "+20 100 XXX 0000", "expires_in_s": 300, "demo_code": "4321"}
    if path == "/otp/verify":
        return {"verified": json["code"] == "4321", "session": "tok"}
    if path == "/cards":
        return [{"last4": "9847", "type": "debit", "status": "active"}, {"last4": "1122", "type": "credit", "status": "active"}]
    if path.endswith("/block"):
        return {"last4": path.split("/")[2], "status": "blocked", "block_reason": json["reason"]}
    return {}


async def allow(text, *_a, **_k):
    seen.append(text)
    return {"allowed": True, "rail": None, "latency_ms": 1}


async def no_log(*_a, **_k):
    return None


heard_as: dict = {}             # what the speech service answers for the next recording


class FakeSpeechService:
    """Stands in for httpx.AsyncClient on the call to the speech-to-text service."""
    def __init__(self, *_a, **_k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def post(self, *_a, **_k):
        class Answer:
            json = staticmethod(lambda: dict(heard_as))
        return Answer()


d4.llm.chat, d4.platform.mockbank, d4.platform.guard_input, d4.platform.guard_output, d4.log_event = fake_chat, fake_bank, allow, allow, no_log


def session(verified: bool = False, said: str | None = None) -> str:
    """A fresh session; `said` is the agent reply the customer is about to answer."""
    sid = f"s{len(d4.SESSIONS)}"
    d4.SESSIONS[sid] = {"customer": {"id": "C0001", "name_ar": "عميل", "name_en": "Customer"}, "token": "tok" if verified else None,
                        "verified": verified, "created": 0, "messages": [{"role": "assistant", "content": said}] if said else []}
    return sid


async def turn(sid: str, text: str, *steps, code: str | None = None) -> dict:
    """One customer turn with the model's steps scripted; `code` is a keypad entry."""
    script[:] = steps
    bank_calls.clear()
    forced.clear()
    return await d4.turn(d4.TurnIn(session_id=sid, text=text, code=code))


def tool_result(out: dict, name: str) -> dict:
    return next(e["result"] for e in out["events"] if e["type"] == "tool" and e["name"] == name)


def blocked_at_bank() -> list[str]:
    return [p for _, p in bank_calls if p.endswith("/block")]


async def main() -> int:
    print("The one-time code bypasses the models")
    check("verify_otp" not in json.dumps(d4.OPENAI_TOOLS), "the agent has no tool that takes a code")
    sid = session()
    await turn(sid, "I lost my card", [call("send_otp")], "Please enter the code.")
    seen.clear()
    out = await turn(sid, "The code is 4321", "You are verified.")
    check(out["verified"] and ("POST", "/otp/verify") in bank_calls, "a code typed in the chat is checked by the bank and verifies the customer")
    check(not any("4321" in x for x in seen) and any("••••" in x for x in seen), "no model was sent the code: the agent and the guardrail got it masked")
    check(any("bank confirmed it" in x for x in seen), "the agent is told only that the bank confirmed the code")

    sid = session()
    await turn(sid, "I lost my card", [call("send_otp")], "Please enter the code.")
    seen.clear()
    out = await turn(sid, "", "You are verified.", code="4321")
    check(out["verified"] and not any("4321" in x for x in seen), "a code entered on the keypad verifies without reaching a model")

    sid = session()
    await turn(sid, "I lost my card", [call("send_otp")], "Please enter the code.")
    seen.clear()
    out = await turn(sid, "الكود ٩ ٩ ٩ ٩", "الكود مش مظبوط.")
    check(not out["verified"] and any("bank rejected it" in x for x in seen) and not any("9999" in x or "9 9 9 9" in x for x in seen),
          "a wrong code, spaced out and in Arabic-Indic digits as a transcript gives it, is rejected and still masked")

    sid = session(verified=True, said="Shall I block the card ending 9847?")
    seen.clear()
    await turn(sid, "yes, 9847", [call("block_card", last4="9847", reason="lost")], "Done.")
    check(any("9847" in x for x in seen) and ("POST", "/otp/verify") not in bank_calls, "with no code pending, digits are left alone")

    print("Confirm before block")
    sid = session(verified=True, said="You are verified.")
    out = await turn(sid, "block my card", [call("block_card", last4="9847", reason="lost")], "Shall I block the card ending 9847?")
    check(not blocked_at_bank(), "a block the customer was not asked about is held")
    check(tool_result(out, "block_card").get("confirmation_required") is True, "the model is told to ask for confirmation")
    out = await turn(sid, "yes", [call("block_card", last4="9847", reason="lost")], "Done.")
    check(blocked_at_bank() == ["/cards/9847/block"], "after the agent named the card and the customer answered, it is blocked")

    sid = session(verified=True, said="Shall I block the card ending 9847?")
    await turn(sid, "yes", [call("block_card", last4="1122", reason="lost")], "Shall I block the card ending 1122?")
    check(not blocked_at_bank(), "a different card from the one the customer was asked about is held")

    sid = session(verified=True, said="هل أوقف البطاقة المنتهية بـ ٩٨٤٧؟")
    await turn(sid, "أيوه", [call("block_card", last4="9847", reason="lost")], "تم.")
    check(blocked_at_bank() == ["/cards/9847/block"], "a card named in Arabic-Indic digits counts as asked")

    print("Promises are kept")
    sid = session()
    await turn(sid, "I lost my card", [call("send_otp")], "Please enter the code.")
    await turn(sid, "4321", "هشوف البطاقات اللي عند حضرتك", [call("get_cards")], "عندك بطاقة آخرها 9847، أوقفها؟")
    check(forced == [False, True, False] and ("GET", "/cards") in bank_calls, "a promise with no tool call is retried with a tool call required")
    sid = session()
    await turn(sid, "I lost my card", [call("send_otp")], "هبعتلك كود دلوقتي")
    check(forced == [False, False] and bank_calls.count(("POST", "/otp/send")) == 1, "after an action ran, a promise-like reply does not force a second one")

    print("One greeting per conversation")
    sid = session()
    out = await turn(sid, "السلام عليكم، عايز أعرف رسوم البطاقة", "وعليكم السلام يا محمد، ازيك يا فندم؟ الرسوم خمسين جنيه.")
    check(out["reply"].startswith("وعليكم السلام يا محمد، ازيك"), "the first reply keeps its greeting")
    out = await turn(sid, "طب ورسوم بطاقة الائتمان؟", "ازيك يا فندم، رسوم بطاقة الائتمان مية جنيه.")
    check(out["reply"] == "رسوم بطاقة الائتمان مية جنيه.", "a greeting on a later reply is removed")
    out = await turn(sid, "تمام شكراً", "تحت أمرك يا فندم في أي وقت.")
    check(out["reply"] == "تحت أمرك يا فندم في أي وقت.", "a reply that does not open with a greeting is left alone")

    print("No silent turns")
    sid = session()
    out = await turn(sid, "I lost my card", [call("send_otp")], "", "Please enter the code.")
    check(out["reply"] == "Please enter the code.", "an empty answer after a tool result is asked for again")
    sid = session()
    out = await turn(sid, "I lost my card", ("I sent you a code, please enter it.", [call("send_otp")]), "")
    check(out["reply"] == "I sent you a code, please enter it.", "words written in the same message as a tool call are the reply when nothing follows")
    sid = session(verified=True, said="You are verified.")
    out = await turn(sid, "block it", ("Your card 9847 is blocked.", [call("block_card", last4="9847", reason="lost")]), "", "Shall I block the card ending 9847?")
    check(out["reply"] == "Shall I block the card ending 9847?" and not blocked_at_bank(), "but not when the tool refused what those words announce")
    sid = session()
    out = await turn(sid, "I lost my card", [call("send_otp")], 'call:handoff_to_human{}', "Please enter the code.")
    check(out["reply"] == "Please enter the code." and ("POST", "/handoff") not in bank_calls, "a tool call returned as text is neither shown nor run")

    sid = session()
    out = await turn(sid, "فقدت بطاقتي", [call("send_otp")], "1.  **Customer Name:** محمد 2.  **Action:** ask for the code", "Please enter the code.")
    check(out["reply"] == d4.ASK_CODE["ar"], "planning notes, or English to an Arabic speaker, are replaced by a plain request for the code")

    print("A recording that was not heard clearly")
    real_client, d4.httpx.AsyncClient = d4.httpx.AsyncClient, FakeSpeechService
    sid = session()
    seen.clear()
    script[:] = []
    heard_as.update(text="انا بحب ازاي اعمل ا", heard=False, confidence=0.31, model="QwenCleo-ASR", latency_ms=1)
    out = await d4.turn(d4.TurnIn(session_id=sid, audio_b64="AAAA"))
    check(out["reply"] == d4.UNCLEAR["ar"] and not seen and not d4.SESSIONS[sid]["messages"]
          and not any(e["type"] == "transcript" for e in out["events"]),
          "the customer is asked to repeat or type; the made-up sentence is not shown and reaches no model")
    heard_as.update(text="عايز أعرف مواعيد الفرع", heard=True, confidence=0.93)
    script[:] = ["الفروع بتشتغل من 8 ونص الصبح."]
    out = await d4.turn(d4.TurnIn(session_id=sid, audio_b64="AAAA"))
    check(any(e["type"] == "transcript" and e["text"] == "عايز أعرف مواعيد الفرع" for e in out["events"]) and out["reply"].startswith("الفروع"),
          "a recording that was heard goes through as before")
    d4.httpx.AsyncClient = real_client

    print("Replies start with the answer")
    sid = session(said="ازيك يا فندم، أقدر أساعدك في إيه؟")
    out = await turn(sid, "ايه حد السحب اليومي؟", "تمام يا فندم، الحد الأقصى للسحب 30 ألف جنيه في اليوم.")
    check(out["reply"].startswith("الحد الأقصى للسحب"), "an opening «تمام يا فندم،» is dropped")
    out = await turn(sid, "شكرا", "تمام يا فندم.")
    check(out["reply"] == "تمام يا فندم.", "but a reply that is nothing else is kept")

    print("Speech")
    say = d4.speech.normalize
    check("خمسميت جنيه" in say("الرسوم 500 جنيه", "ar") and "ميت جنيه" in say("الرسوم 100 EGP", "ar"), "a hundred right before the pounds takes its Egyptian ending")
    check("خمسمية وخمسين جنيه" in say("550 جنيه", "ar") and "عشرين ألف جنيه" in say("20,000 جنيه", "ar"), "but not when more follows, and thousands are spelled out")
    lex = d4.speech.lexicon()
    check(lex.get("ميت") == "مِيت" and lex.get("ميتين") == "مِيتِين" and lex.get("بدقة") == "بِدِقَة", "the vowels go to the voice as a lexicon: it deletes them from the text")
    spoken = say("مبادرة الـ 8%: الوحدة لحد مليون و100 ألف جنيه أو 2.5 مليون جنيه، والمقدم 22.5% أو 8.4٪", "ar")
    check("مبادرة التمنية في المية" in spoken and "اتنين وعشرين ونص في المية" in spoken and "تمنية فاصلة أربعة في المية" in spoken and "%" not in spoken and "٪" not in spoken,
          "a percentage is always في المية, a half is ونص, and الـ is joined to the number")
    check("اتنين ونص مليون جنيه" in spoken and "مليون وميت ألف جنيه" in spoken, "2.5 million is اتنين ونص مليون, and a hundred before ألف takes its Egyptian ending")
    check("اتنين جنيه ونص" in say("2.5 جنيه", "ar") and "تسعتاشر وربع" in say("19.25%", "ar") and "سبعة وعشرين وتلات أرباع" in say("27.75%", "ar"), "quarters too, and in money: جنيه ونص, not خمسين قرش")
    loan = say("من سن 21 لحد 65 سنة. لصافي دخل لحد 13,000 جنيه للفرد و18,000 للأسرة، وقيمة الوحدة لحد 1,100,000 أو 1,400,000 جنيه، والمدة من 5 لـ 30 سنة.", "ar")
    check("من سن واحد وعشرين لحد خمسة وستين سنة" in loan and "تلتاشر ألف جنيه للفرد وتمنتاشر ألف للأسرة" in loan
          and "مليون وميت ألف أو مليون وربعميت ألف جنيه" in loan and "من خمسة لتلاتين سنة" in loan and not any(ch.isdigit() for ch in loan),
          "every number is written out in Egyptian words, also one joined to و or لـ: none is left for the voice to read")
    check("مليون وربعميت ألف جنيه" in say("قيمة الوحدة 1.4 مليون جنيه", "ar") and "مليون ونص" in say("1.5 مليون", "ar") and "تلتاشر ألف" in say("13 ألف", "ar")
          and "تلات تلاف" in say("3 آلاف", "ar"), "1.4 million is مليون وربعميت ألف: a number and its ألف or مليون are said as one number")
    check("خلال خمس أيام عمل" in say("هيوصلك خلال 5 أيام عمل", "ar") and "خمسميت عميل" in say("عندنا 500 عميل", "ar") and "وبتلات كروت" in say("وبـ 3 كروت", "ar"),
          "a number takes its short form before what it counts")
    check("تلاتين نوفمبر ألفين وستة وعشرين" in say("العرض لحد 2026-11-30", "ar") and "سنة ألفين وخمسة وعشرين" in say("من سنة 2025", "ar"), "a date and a year are said, not read digit by digit")
    check(lex.get("وعشرين") == "وَعِشْرِين" and lex.get("لتلاتين") == "لِتَلَاتِين" and lex.get("التمنية") == "التَّمَنْيَة" and lex.get("الأقصى") == "الْأَقْصَى",
          "number words carry their vowels in every joined form, and so does الأقصى")
    check(lex.get("تلتاشر") == "تَلَتَاشَّر" and lex.get("وتلتاشر") == "وَتَلَتَاشَّر" and lex.get("دخل") == "دَخْلْ" and lex.get("الصراف") == "الصَرَّاف"
          and lex.get("للصراف") == "لِلصَرَّاف" and lex.get("هبعتلك") == "هَبْعتلَكْ", "words corrected by ear are said as they were written down")
    check(lex.get("المية") == "الْمِيَّة" and lex.get("ونص") == "وَنُصّ" and lex.get("وميت") == "وَمِيت", "the words written for a percentage, a half and a joined hundred carry their vowels")
    check(lex.get("مقدم") == "مُقَدَّم" and lex.get("والمقدم") == "وَالْمُقَدَّم" and lex.get("بمقدم") == "بِمُقَدَّم" and lex.get("للمقدم") == "لِلْمُقَدَّم",
          "a listed word keeps its vowels behind و، ب، ل and ال: the down payment is مُقَدَّم however it is joined")
    check(lex.get("للسحب") == "لِلسَّحْب" and lex.get("الدخل") == "الدَّخْلْ" and lex.get("وللدخل") == "وَلِلدَّخْلْ", "ال is doubled into a sun letter, also for a word listed with its article")
    check(not d4.speech.careful(say("المقدم والقسط على مدة القرض", "ar")), "listed banking words do not slow the voice down: only [careful] words and numbers do")
    check(d4.speech.careful(say("هراجع بياناتك بدقة", "ar")) and d4.speech.careful_words(say("الحد الأقصى للسحب", "ar")) == ["الأقصى"],
          "a sentence with a [careful] word is spoken on the exact setting")
    check(d4.speech.careful_words(say("الرسوم 500 جنيه والمقدم 15%", "ar")) == ["المية", "خمستاشر", "خمسميت"], "and so is a sentence with a number: the fast setting slurs or drops it")
    check(say("رصيدك 247193.44 جنيه", "ar").endswith("جنيه وأربعة وأربعين قرش"), "piastres are named")
    check("آخرها تسعة تمنية أربعة سبعة" in say("بطاقة آخرها 9847", "ar") and "T، اتنين ستة واحد، صفر واحد واحد" in say("رقم الطلب T-261011-30551", "ar"),
          "a card ending and a ticket number are read digit by digit")
    en = say("Your card ending 4821 is blocked. The fee is 500 EGP, or EGP 20,000 a day at 2.5%, by the 21st. Ticket T-261011-30551.", "en")
    check("ending four eight two one is" in en and "five hundred Egyptian pounds" in en and "or twenty thousand Egyptian pounds a day" in en
          and "two point five percent" in en and "twenty-first" in en and "T, two six one, zero one one, three zero five, five one" in en
          and "one thousand two hundred fifty US dollars" in say("Limit 1250 USD", "en")
          and not any(ch.isdigit() for ch in en), "in English every number is written out in English words: the voice reads a digit as Arabic")
    check("ديبت كارد" in say("بطاقة واحدة (debit) آخرها", "ar") and "(" not in say("بطاقة (Debit Card)", "ar"), "card types are spelled by sound and brackets dropped")
    check(d4.speech.reword("عشان نتحقق من هويتك وهنتحقق تاني") == "عشان نتأكد من هويتك وهنتأكد تاني", "unwanted words are replaced in the reply itself, also inside a word")

    failed = [label for ok, label in results if not ok]
    print(f"d4 rules: {len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
