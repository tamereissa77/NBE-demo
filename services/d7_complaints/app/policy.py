"""D7 reply policy that comes from data instead of from main.py.

Switched on by data/seed/d7/policy.json; without that file the service keeps the team baseline. It adds:
  - fixed English team names, so an English reply never carries a name the model translated by itself;
  - a public-reply mode for social media: short, no customer name, no case details, move to private messages;
  - extra banned phrases (a first-response SLA must not be worded as a final reply);
  - the checks behind those rules, run on every draft and on every reviewer decision.
The file is read on each call, so editing it needs no restart.
"""
import json
import re
from pathlib import Path

CONFIG = Path("/data/seed/d7/policy.json")

SALUTATION = r"عزيز[يت]|عزيزنا|الأستاذ|الاستاذ|السيدة?\b|\bDear\b|\bMr\b|\bMrs\b|\bMs\b"
PRIVATE = r"رسال\S*\s+خاص|الرسائل الخاصة|على الخاص|private message|direct message|\bDM\b"
TEAM_WORD = r"\b(department|division|unit)\b"


def load() -> dict | None:
    return json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else None


def team_en(pol: dict, topic: str) -> str | None:
    return pol.get("teams_en", {}).get(topic)


def is_public(pol: dict, channel: str) -> bool:
    return channel in pol.get("public_reply", {}).get("channels", [])


def public_prompt(pol: dict, cid: str, text: str, lang_note: str) -> str:
    """The drafting prompt for a reply that anyone can read. The customer's name is deliberately not passed."""
    rules = pol["public_reply"]["rules"]
    return ("اكتب رداً عاماً قصيراً يُنشر على وسائل التواصل الاجتماعي على الشكوى التالية. "
            "أخرج نص الرد فقط، بدون أي مقدمة أو عنوان أو بدائل أو تنسيق Markdown.\n"
            f"رقم الشكوى: {cid}.\n"
            "قواعد الرد العام (إلزامية):\n" + "\n".join(f"- {r}" for r in rules) + f"\n{lang_note}\n\n"
            f"الشكوى:\n{text}")


def violations(pol: dict, text: str, *, cid: str, channel: str, language: str, topic: str, customer_name: str) -> list[str]:
    """Rule checks on a reply. Each item is a sentence the drafting model and the reviewer can both read."""
    out = [f"banned phrase: {p}" for p in pol.get("banned_extra", []) if re.search(p, text, re.I)]

    official = team_en(pol, topic)
    if language == "en" and official and official not in text and re.search(TEAM_WORD, text, re.I):
        out.append(f"team name is not the official one; write it exactly as: {official}")

    if is_public(pol, channel):
        limit = pol["public_reply"].get("max_chars", 320)
        if len(text) > limit:
            out.append(f"public reply is {len(text)} characters; the limit is {limit}")
        name_parts = [p for p in re.split(r"\s+", customer_name) if len(p) >= 3]
        if re.search(SALUTATION, text, re.I) or any(p in text for p in name_parts):
            out.append("public reply names or personally greets the customer")
        if re.search(r"[0-9٠-٩]", text.replace(cid, "")):
            out.append("public reply contains figures other than the complaint number")
        if cid not in text:
            out.append("public reply does not state the complaint number")
        if not re.search(PRIVATE, text, re.I):
            out.append("public reply does not move the customer to private messages")
    return out
