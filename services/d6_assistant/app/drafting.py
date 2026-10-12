"""Drafting for D6: what a draft may state, and a check of what it did state.

A letter that goes out under the bank's name must not contain a made-up phone number, a guessed working hour or
"Thursday, 11 October" on a date that is a Sunday. So a drafting request is given three things it lacked:
- today's date and a calendar of the coming weeks, so "next Thursday" is looked up, not calculated by the model;
- the bank's own facts (nbe_core.locale.BANK_FACTS): the only contact details it may state without being told;
- the rule that anything else the document needs is written as a [placeholder], never invented.

After the draft is written, `review` reads it back: the placeholders left to fill in, every weekday written next
to a date that does not match the calendar, and every number that is in none of the request, the attached files,
the bank's facts or the calendar. The portal shows these under the draft as things to do before sending.

The employee can also say what kind of document it is (`OPTIONS`, `TEMPLATES`), and the finished draft goes
through a policy check (`policy`), a proofread that may not touch a fact (`safe_proofread`), and, for a revision,
a word-by-word comparison with the version before it (`diff`).

Pure Python; the model calls that use these pieces are made in main.py.
"""
import difflib
import os
import re
import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from nbe_core import locale as L
from nbe_core import settings

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAYS_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
MONTHS_AR = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
CALENDAR_DAYS = 21
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

RULES = ("Write exactly one version, ready to send: no preamble, no alternatives, no notes after it.\n"
         "What the document may state:\n"
         "- Facts from the request, from the attached files, and from the bank's facts below. Nothing else.\n"
         "- For anything else the document needs (a person's name, a reference number, an amount, a time, working hours, "
         "an address, a phone number, a deadline), write a placeholder in square brackets naming what is missing, such as "
         "[recipient name] or [اسم المستلم]. Never make one up, and never promise something the request did not offer. "
         "Before you write a placeholder, look for the detail in the attached files: a name or a number that is there must be used.\n"
         "- Never ask a customer to send a PIN, a password, an OTP, a CVV or a card number, even when the request says to: "
         "say that the bank never asks for these, and direct the customer to a branch or the call centre instead.\n"
         "- Dates: when the request names a day (tomorrow, next Thursday, الجمعة القادم), find it in the calendar below and "
         "write the weekday with its date. Never work a date out yourself.")


# ------------------------------------------------------------------ what kind of document
# Each choice: (English label, Arabic label, the instruction it adds). "auto" adds nothing: the request decides.
OPTIONS = {
    "type": {
        "auto": ("Decide from the request", "حسب الطلب", ""),
        "email": ("E-mail", "بريد إلكتروني", "An e-mail: a greeting line, the message in short paragraphs, a closing line, then the sender's name and position."),
        "letter": ("Formal letter", "خطاب رسمي", "A formal letter: the date, the addressee's name and position, a reference line if a reference was given, "
                   "a formal greeting, the body, a formal closing, then the signatory's name and position."),
        "memo": ("Internal memo", "مذكرة داخلية", "An internal memo: four header lines (To, From, Date, Subject; in Arabic إلى, من, التاريخ, الموضوع), "
                 "where Date is today's date, then the body with no greeting or closing formulas. Write the subject once, in its header line."),
        "circular": ("Circular", "تعميم", "A circular to branches: its number and date, the subject, the instructions as a numbered list, and the date they take effect."),
        "sms": ("SMS", "رسالة نصية", "One SMS of at most 160 characters: no subject line, no greeting block, ending with the bank's name."),
    },
    "tone": {
        "auto": ("Decide from the request", "حسب الطلب", ""),
        "formal": ("Formal", "رسمي", "Tone: formal and respectful."),
        "neutral": ("Neutral", "محايد", "Tone: plain and businesslike."),
        "friendly": ("Warm", "ودّي", "Tone: warm and personal, still professional."),
    },
    "length": {
        "auto": ("Decide from the request", "حسب الطلب", ""),
        "short": ("Short", "قصير", "Length: at most 80 words in the body."),
        "medium": ("Medium", "متوسط", "Length: 80 to 160 words in the body."),
        "long": ("Detailed", "مفصّل", "Length: 160 to 300 words in the body."),
    },
    "audience": {
        "auto": ("Decide from the request", "حسب الطلب", ""),
        "customer": ("A customer", "عميل", "Reader: a customer. Plain words, no internal jargon or system names, and say what the customer should do next."),
        "staff": ("Staff", "الموظفون", "Reader: bank staff. Say exactly what they must do and by when."),
        "management": ("Senior management", "الإدارة العليا", "Reader: senior management. Lead with the decision or the point, then the support for it."),
        "regulator": ("A regulator", "جهة رقابية", "Reader: a regulator. Precise, complete, and nothing that is not established."),
    },
    "language": {
        "auto": ("Language of the request", "لغة الطلب", ""),
        "ar": ("Arabic", "العربية", ""),
        "en": ("English", "الإنجليزية", ""),
        "both": ("Arabic and English", "العربية والإنجليزية", ""),
    },
}
# Ready-made starts for common bank documents: the request the employee completes, and the parts the draft must have.
TEMPLATES = [
    {"id": "apology", "type": "letter", "en": "Apology to a customer", "ar": "اعتذار لعميل",
     "request_en": "Write a letter to a customer apologising for [what went wrong], and say what the bank is doing about it: [action].",
     "request_ar": "اكتب خطاباً لعميل للاعتذار عن [ما حدث]، مع توضيح ما يقوم به البنك: [الإجراء].",
     "outline": "1) what happened, stated plainly; 2) the apology; 3) what the bank is doing or offering; 4) how to reach the bank."},
    {"id": "complaint_reply", "type": "letter", "en": "Reply to a complaint", "ar": "رد على شكوى",
     "request_en": "Write a reply to a customer's complaint about [subject of the complaint]. Outcome: [what was found or decided].",
     "request_ar": "اكتب رداً على شكوى عميل بخصوص [موضوع الشكوى]. النتيجة: [ما تم التوصل إليه].",
     "outline": "1) acknowledge the complaint and its reference; 2) what was looked into; 3) the outcome; 4) what happens next and by when; 5) how to escalate."},
    {"id": "meeting", "type": "email", "en": "Meeting invitation", "ar": "دعوة لاجتماع",
     "request_en": "Write an invitation to [who] for a meeting about [topic] on [day] at [time] in [place].",
     "request_ar": "اكتب دعوة إلى [المدعوون] لاجتماع بخصوص [الموضوع] يوم [اليوم] الساعة [الوقت] في [المكان].",
     "outline": "1) purpose of the meeting; 2) date, time and place on their own lines; 3) the agenda as a short list; 4) what to prepare; 5) who to confirm attendance with."},
    {"id": "maintenance", "type": "memo", "en": "System maintenance notice", "ar": "إشعار صيانة نظام",
     "request_en": "Write a notice to [who] that [system] will be unavailable on [day] from [time] to [time].",
     "request_ar": "اكتب إشعاراً إلى [الجهة] بأن [النظام] سيتوقف يوم [اليوم] من [الوقت] إلى [الوقت].",
     "outline": "1) which system and when; 2) what will not be available; 3) what staff should do before and during it; 4) who to contact."},
    {"id": "documents", "type": "email", "en": "Request for documents", "ar": "طلب مستندات",
     "request_en": "Write to [who] asking for [documents] for [purpose], needed by [day].",
     "request_ar": "اكتب إلى [الجهة] لطلب [المستندات] لغرض [الغرض]، مطلوبة قبل [اليوم].",
     "outline": "1) what is needed, as a list; 2) why; 3) the deadline; 4) how to send it."},
]


def options(lang: str) -> dict:
    """The choices and templates for the portal, labelled in its language."""
    i = 1 if lang == "ar" else 0
    return {"options": {name: [{"id": k, "label": v[i]} for k, v in choices.items()] for name, choices in OPTIONS.items()},
            "templates": [{"id": t["id"], "label": t["ar" if lang == "ar" else "en"], "type": t["type"],
                           "request": t["request_ar" if lang == "ar" else "request_en"]} for t in TEMPLATES]}


def form(opts: dict, lang: str) -> str:
    """The employee's choices as instructions. A missing or unknown choice counts as "auto"."""
    lines = [OPTIONS[name][opts.get(name) or "auto"][2] for name in ("type", "tone", "length", "audience") if (opts.get(name) or "auto") in OPTIONS[name]]
    template = next((t for t in TEMPLATES if t["id"] == opts.get("template")), None)
    if template:
        lines.append(f"Follow this outline: {template['outline']}")
    if (opts.get("type") or "auto") not in ("sms", "memo", "circular"):          # those carry their subject in their own header, or have none
        lines.append("Begin with one line `الموضوع: ...`" if lang == "ar" else "Begin with one line `Subject: ...`")
    if opts.get("language") == "both":
        lines.append("Write the whole document twice: first in Arabic, then a line with only `---`, then the same document in English.")
    return "\n".join(f"- {ln}" for ln in lines if ln)


def today() -> date:
    return datetime.now(ZoneInfo(os.getenv("TZ", "Africa/Cairo"))).date()


def spell(d: date, lang: str) -> str:
    return f"{DAYS_AR[d.weekday()]} {d.day} {MONTHS_AR[d.month - 1]} {d.year}" if lang == "ar" else f"{DAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]} {d.year}"


def date_line(lang: str) -> str:
    """One line for every task: the assistant otherwise has no idea what day it is."""
    return f"اليوم هو {spell(today(), 'ar')}." if lang == "ar" else f"Today is {spell(today(), 'en')}."


def context(lang: str, opts: dict | None = None, current: str = "") -> str:
    """The drafting rules, the calendar and the bank's facts, as a block for the system prompt. The calendar and the
    facts are written in the language of the request only: a prompt half in Arabic pulls an English draft into Arabic."""
    t, ar = today(), lang == "ar"
    days = []
    for i in range(CALENDAR_DAYS + 1):
        d = t + timedelta(days=i)
        note = (" (اليوم)" if ar else " (today)") if i == 0 else (" (غداً)" if ar else " (tomorrow)") if i == 1 else ""
        days.append(f"- {spell(d, lang)}{note}{(' [عطلة نهاية الأسبوع]' if ar else ' [weekend]') if d.weekday() in L.WEEKEND else ''}")
    pick = lambda label: label.split(" / ")[-1 if ar else 0]  # noqa: E731
    facts = "\n".join(f"- {pick(label)}: {value}" for label, value in [("Name / الاسم", settings.bank_ar if ar else settings.bank_en), *L.BANK_FACTS])
    language = ("Write the document in Arabic (Modern Standard Arabic)" if ar else "Write the document in English") + \
        ", unless the request asks for another language."
    shape = form(opts or {}, lang)
    revise = (f"\n\nThis is a revision. The current draft is below. Change only what the employee asks for and keep every other "
              f"sentence word for word; return the whole document.\n=== current draft ===\n{current}\n=== end ===") if current else ""
    return (f"{RULES}\n- {language}" + (f"\n\nThe document:\n{shape}" if shape else "") + revise + "\n\nCalendar (\"next Thursday\" is the first Thursday after today):\n" + "\n".join(days) +
            f"\n\nThe bank's facts (the only details about the bank you may state without being told):\n{facts}")


# ------------------------------------------------------------------ reading a draft back
def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(DIGITS)
    text = re.sub("[ً-ْـ]", "", text).replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = re.sub("[‐-―]", "-", text).replace(" ", " ").replace(" ", " ")
    return re.sub(r"(?<=\d)[,٬](?=\d{3})", "", text).lower()


_WEEKDAYS = {**{n.lower(): i for i, n in enumerate(DAYS)}, **{_plain(n): i for i, n in enumerate(DAYS_AR)}, "الاثنين": 0, "الاحد": 6}
_MONTHS = {**{m.lower(): i + 1 for i, m in enumerate(MONTHS)}, **{_plain(m): i + 1 for i, m in enumerate(MONTHS_AR)}}
_WD, _MO = "|".join(map(re.escape, _WEEKDAYS)), "|".join(map(re.escape, _MONTHS))
_DATED = re.compile(rf"({_WD})\W{{0,25}}?(?:the\s+|الموافق\s+|بتاريخ\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MO})(?:\W+(\d{{4}}))?"
                    rf"|({_WD})\W{{0,25}}?({_MO})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\W+(\d{{4}}))?")


def placeholders(draft: str) -> list[str]:
    """What the draft left for the employee to fill in, in order, without repeats."""
    found = [p.strip() for p in re.findall(r"\[([^\[\]\n]{2,60})\]", draft)]
    return list(dict.fromkeys(p for p in found if not re.fullmatch(r"S\d+|Page \d+|Sheet: .*", p)))


def wrong_weekdays(draft: str) -> list[dict]:
    """Every weekday written next to a date that the calendar disagrees with."""
    out, t = [], today()
    for m in _DATED.finditer(_plain(draft)):
        w, day, month, year = (m.group(1), m.group(2), m.group(3), m.group(4)) if m.group(1) else (m.group(5), m.group(7), m.group(6), m.group(8))
        try:
            d = date(int(year) if year else t.year, _MONTHS[month], int(day))
        except ValueError:
            out.append({"written": m.group(0), "problem": "not a real date"})
            continue
        if not year and d < t - timedelta(days=30):
            d = d.replace(year=d.year + 1)
        if d.weekday() != _WEEKDAYS[w]:
            out.append({"written": m.group(0), "problem": f"that date is a {DAYS[d.weekday()]} / {DAYS_AR[d.weekday()]}"})
    return out


_WD_RAW = "|".join(DAYS + DAYS_AR + ["الإثنين", "الاربعاء", "الاحد"])
_MO_RAW = "|".join(MONTHS + MONTHS_AR + ["ابريل", "اغسطس", "اكتوبر"])
_DATED_RAW = re.compile(rf"(?P<wd>{_WD_RAW})(?P<gap>\W{{0,25}}?(?:the\s+|الموافق\s+|بتاريخ\s+)?)(?P<rest>(?P<d1>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<m1>{_MO_RAW})(?:\W+(?P<y1>\d{{4}}))?"
                        rf"|(?P<m2>{_MO_RAW})\s+(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?(?:\W+(?P<y2>\d{{4}}))?)", re.I)


def fix_weekdays(draft: str) -> tuple[str, int]:
    """A weekday the model put next to a date is looked up, not trusted: where the two disagree, the weekday is
    replaced by the right one (the date, which came from the request or a file, is kept). Returns (text, corrections)."""
    fixed = 0

    def right(m: re.Match) -> str:
        nonlocal fixed
        day, month, year = (m["d1"], m["m1"], m["y1"]) if m["d1"] else (m["d2"], m["m2"], m["y2"])
        t = today()
        try:
            d = date(int(year) if year else t.year, _MONTHS[_plain(month)], int(day))
        except (ValueError, KeyError):
            return m.group(0)
        if not year and d < t - timedelta(days=30):
            d = d.replace(year=d.year + 1)
        if d.weekday() == _WEEKDAYS.get(_plain(m["wd"])):
            return m.group(0)
        fixed += 1
        name = DAYS_AR[d.weekday()] if re.search(r"[\u0600-\u06ff]", m["wd"]) else DAYS[d.weekday()]
        return f"{name}{m['gap']}{m['rest']}"

    return _DATED_RAW.sub(right, draft), fixed


def unsourced(draft: str, sources: str) -> list[str]:
    """Numbers of two or more digits in the draft that are nowhere in `sources` (the request and the conversation,
    the attached files, the bank's facts). Dates are judged by `wrong_weekdays`, so they are left out here."""
    text, ok = _plain(draft), _plain(sources + " " + " ".join(v for _, v in L.BANK_FACTS))
    short = "|".join([m[:3].lower() for m in MONTHS])
    text = re.sub(rf"\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{_MO}|{short})\b(?:\W+\d{{4}})?|(?:{_MO}|{short})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:\W+\d{{4}})?", " ", text)
    text = re.sub(r"\[s\d+\]|\b(?:19|20)\d{2}\b|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}", " ", text)
    out = []
    for n in re.findall(r"\d+(?:\.\d+)?", text):
        core = n.lstrip("0") or "0"
        if len(core) < 2:
            continue
        forms = {core, n} | ({str(int(core) - 12)} if core.isdigit() and 13 <= int(core) <= 23 else set())       # 13:00 for "1 pm"
        if not any(re.search(rf"(?<![\d.]){re.escape(f)}(?!\d|\.\d)", ok) for f in forms):
            out.append(n)
    return list(dict.fromkeys(out))


FOR_REVIEWER = ("The passage numbers are for the employee who reviews the draft and are removed before it is sent: put each one "
                "right after the fact as a bare mark, and never mention the marks or the passages in the wording of the document.")


def clean(draft: str) -> str:
    """The draft as it would be sent: without the passage marks."""
    return re.sub(r"[ \t]*\[S\d+\]", "", draft)


SUBJECT = re.compile(r"^\s*\**\s*(?:subject|الموضوع|re)\s*\**\s*[:：]\s*\**\s*(.+?)\s*\**\s*$", re.I)


def parts(draft: str) -> dict:
    """{subject, body}: the subject is the first line when it is written as one; an SMS has none."""
    lines = draft.strip().split("\n")
    m = SUBJECT.match(lines[0]) if lines else None
    return {"subject": m.group(1).strip() if m else "", "body": "\n".join(lines[1:]).strip() if m else draft.strip()}


# Placeholder policy until the bank supplies its own, as in D7: (rule, pattern). A promise the employee wrote into the
# request is shown to them as theirs to answer for (`requested`); one the model added is repaired and blocks approval.
POLICY = [
    ("asks for a secret (PIN, password, OTP, card number)",
     r"\b(send|share|provide|confirm|give|tell|enter|reply with|forward)\b[^.\n]{0,40}\b(pin|otp|password|cvv|card number)\b"
     r"|(أرسل|ارسل|شارك|زودنا|تزويدنا|موافاتنا|إرسال|ارسال|مشاركة|أدخل)[^.\n]{0,30}(الرقم السري|كلمة المرور|كلمة السر|رمز التحقق|رقم البطاقة|cvv|otp|pin)"),
    ("makes a promise or guarantee",
     r"\bguarantee|\bwe promise|we will refund|you will be refunded|will be compensated|نضمن|مضمون|نتعهد|سنرد المبلغ|سيتم رد المبلغ|سنعوضك|سيتم تعويضك"),
    ("compares the bank with other banks", r"better than (other|any) banks?|unlike other banks|أفضل من (البنوك|بنك|أي بنك)|عكس البنوك الأخرى"),
]


def policy(draft: str, request: str = "", doc_type: str = "") -> list[dict]:
    """Rules the draft breaks: [{rule, found}]."""
    out, body = [], clean(draft)
    for rule, pattern in POLICY:
        for m in re.finditer(pattern, body, re.I):
            asked = rule.startswith("makes a promise") and bool(re.search(re.escape(m.group(0)), request, re.I))
            out.append({"rule": rule, "found": m.group(0), "requested": asked})
            break
    if doc_type == "sms" and len(body) > 160:
        out.append({"rule": "an SMS must be at most 160 characters", "found": f"{len(body)} characters", "requested": False})
    return out


def safe_proofread(before: str, after: str) -> tuple[str, int]:
    """Accept a proofread only if it left every fact alone: the same numbers, the same placeholders, about the same
    length. Returns the text to keep and how many words changed (0 when the proofread was refused or changed nothing)."""
    nums = lambda t: sorted(re.findall(r"\d+(?:[.:/-]\d+)*", _plain(t)))  # noqa: E731
    same_facts = nums(before) == nums(after) and placeholders(before) == placeholders(after)
    if not after.strip() or not same_facts or not 0.9 <= len(after) / max(len(before), 1) <= 1.1:
        return before, 0
    a, b = before.split(), after.split()
    changed = sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if op != "equal")
    return after, changed


def diff(old: str, new: str) -> dict:
    """What a revision changed, word by word: {segments: [{op: same|add|del, text}], changed_share}."""
    a, b = re.findall(r"\s+|\S+", old), re.findall(r"\s+|\S+", new)
    segs, changed = [], 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            segs.append({"op": "same", "text": "".join(a[i1:i2])})
            continue
        if i2 > i1:
            segs.append({"op": "del", "text": "".join(a[i1:i2])})
        if j2 > j1:
            segs.append({"op": "add", "text": "".join(b[j1:j2])})
        changed += sum(1 for w in a[i1:i2] + b[j1:j2] if w.strip())
    words = sum(1 for w in a + b if w.strip())
    return {"segments": segs, "changed_share": round(changed / max(words, 1), 2)}


def blocking(report: dict) -> list[str]:
    """What must be dealt with before a draft can be approved."""
    out = []
    if report["placeholders"]:
        out.append(f"{len(report['placeholders'])} placeholder(s) not filled in")
    if report["wrong_weekdays"]:
        out.append("a weekday does not match its date")
    if any(not p["requested"] for p in report["policy"]):
        out.append("a policy rule is broken")
    return out


def review(draft: str, sources: str, request: str = "", doc_type: str = "") -> dict:
    return {**parts(clean(draft)), "policy": policy(draft, request, doc_type), "clean": clean(draft), "placeholders": placeholders(draft), "wrong_weekdays": wrong_weekdays(draft), "unsourced_figures": unsourced(draft, sources)}
