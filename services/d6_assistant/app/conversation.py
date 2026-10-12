"""Conversations for D6 chat: the server keeps the history, so a follow-up question has what it needs.

Before this, the browser held the conversation and sent the last six messages with each question. A fact given
earlier than that was gone, a page reload lost everything, and the router judged each message on its own.

A conversation keeps every message. What the model is shown is bounded: the recent messages word for word, up to
HISTORY_CHARS, and running notes on everything older. Notes are only ever added to: each batch of messages that
ages out gets its own notes, appended to the earlier ones, because a model asked to rewrite its notes every time
can drop the oldest facts. Only when the notes themselves grow past NOTES_CHARS are they merged. Notes are taken
in batches (the word-for-word part is cut back to 60% of the budget), so most turns cost no extra model call.

In memory, like uploaded files (demo scope): conversations survive a page reload, not a restart of the service.
"""
import os
import re
import time
import uuid

from nbe_core import llm
from nbe_core.text import detect_lang
from nbe_core.trace import Trace

HISTORY_CHARS = int(os.getenv("D6_HISTORY_CHARS", "8000"))     # recent messages shown to the model word for word
KEEP_LAST = 4                                                  # always word for word, however long they are
NOTES_CHARS = 2500                                             # notes longer than this are merged into a shorter set
STORE: dict[str, dict] = {}

SUMMARISE = ("Below is part of a conversation between a bank employee and an AI assistant, which will no longer be shown to "
             "the assistant in full. Write the notes the assistant needs to continue the conversation, in at most 150 words.\n"
             "Keep exactly: every fact the employee stated about themselves or their work (names, dates, times, numbers, codes, "
             "places), their preferences and instructions, and one line per request saying what was asked and what was produced.\n"
             "Write the notes in the language the employee used. Notes only, no preamble.")
MERGE = ("These are notes on the earlier part of a conversation between a bank employee and an AI assistant. Rewrite them in at "
         "most 250 words. Every fact the employee stated (names, dates, times, numbers, codes, places, preferences) must survive "
         "word for word; shorten or drop the lines about what was requested and produced first. Notes only, no preamble.")


def new() -> str:
    cid = uuid.uuid4().hex[:12]
    STORE[cid] = {"messages": [], "summary": "", "summarised": 0, "last": None, "files": [], "drafts": [], "summary_source": None, "created": time.time()}
    return cid


def get(cid: str | None) -> dict | None:
    return STORE.get(cid) if cid else None


def view(conv: dict) -> dict:
    """What the portal needs to draw the conversation again after a page reload."""
    return {"messages": [{k: m[k] for k in ("role", "content", "reply") if k in m} for m in conv["messages"]], "files": conv["files"]}


def language(text: str, previous: str | None) -> str:
    """'ar' or 'en' for this message. A message with no language of its own (an acronym, a number, only code:
    "OTP?", "SWIFT vs IBAN?") keeps the language the conversation is in instead of counting as English."""
    prose = re.sub(r"```.*?```|`[^`]*`", " ", text, flags=re.S)
    if re.search(r"[؀-ۿ]", prose):
        return detect_lang(prose)
    english_words = [w for w in re.findall(r"[A-Za-z]{3,}", prose) if not w.isupper()]
    return previous if previous and not english_words else "en"


def add(conv: dict, question: str, answer: str, reply: dict, last: dict, files: list[dict]) -> None:
    conv["messages"] += [{"role": "user", "content": question}, {"role": "assistant", "content": answer, "reply": reply}]
    conv["last"], conv["files"] = last, files


async def context(conv: dict, trace: Trace) -> tuple[list[dict], str]:
    """(messages to show word for word, summary of everything before them), rewriting the summary when the
    word-for-word part has outgrown HISTORY_CHARS."""
    msgs, done = conv["messages"], conv["summarised"]
    size = lambda ms: sum(len(m["content"]) for m in ms)  # noqa: E731
    if size(msgs[done:]) > HISTORY_CHARS and len(msgs) - done > KEEP_LAST:
        cut = len(msgs) - KEEP_LAST                     # newest messages that fit the budget stay; the rest is summarised
        while cut - 2 >= done + 2 and size(msgs[cut - 2:]) <= 0.6 * HISTORY_CHARS:
            cut -= 2
        older = "\n\n".join(f"{'Employee' if m['role'] == 'user' else 'Assistant'}: {m['content'][:1500]}" for m in msgs[done:cut])
        res = await llm.chat([{"role": "user", "content": f"{SUMMARISE}\n\nConversation:\n{older}"}], max_tokens=350, temperature=0)
        conv["summary"], conv["summarised"] = f"{conv['summary']}\n{res.text.strip()}".strip(), cut
        trace.add("memory", f"Took notes on {cut - done} older messages to keep them in mind", conv["summary"], res.latency_ms)
        if len(conv["summary"]) > NOTES_CHARS:
            res = await llm.chat([{"role": "user", "content": f"{MERGE}\n\n{conv['summary']}"}], max_tokens=550, temperature=0)
            conv["summary"] = res.text.strip()
            trace.add("memory", "Merged the notes on the earlier conversation", conv["summary"], res.latency_ms)
    return [{"role": m["role"], "content": m["content"]} for m in msgs[conv["summarised"]:]], conv["summary"]
