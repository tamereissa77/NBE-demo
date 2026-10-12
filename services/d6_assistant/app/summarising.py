"""Summaries for D6: everyday documents (a note, minutes, a policy, an e-mail thread, a spreadsheet, several
files), in the form the employee asks for. Legal analysis (clauses, risks, comparison with the approved
template) belongs to D5 and is not repeated here: a contract or ruling is summarised plainly, with a pointer.

What makes a summary trustworthy, and where each part lives:
- It covers the whole document. A source too long for one prompt is summarised section by section and the
  section notes are then combined (`sections`); the reply says what was covered.
- Every point can be traced. Pasted text is cut into numbered passages like an attached file (`pasted`), so the
  model cites [S3] either way and the evidence checks of file chat apply.
- Every point is checked against the source by a second reading (`CHECK`), which catches what a figure check
  cannot: a relation turned round ("from 16 to 23" becoming "during 16 to 23"), a task given to the wrong person.
  A point found wrong is repaired once.
- The employee chooses the form, length, reader, language and focus (`OPTIONS`).

Pure Python; the model calls that use these pieces are made in main.py.
"""
import re

from app import evidence

SECTION_CHARS = 12000      # of source text per section when a document is summarised in sections

# Each choice: (English label, Arabic label, the instruction it adds). "auto" adds nothing: the request decides.
OPTIONS = {
    "form": {
        "auto": ("Decide from the request", "حسب الطلب", ""),
        "executive": ("Executive summary", "ملخص تنفيذي", "Three sentences at most: what this is, what matters most, what has to be done."),
        "key_points": ("Key points", "أهم النقاط", "The key points as a bulleted list, the most important first."),
        "actions": ("Action items", "المهام المطلوبة", "Only the action items, as a Markdown table with the columns Action, Who, By when "
                    "(in Arabic: المهمة, المسؤول, الموعد). Write 'not stated' (غير مذكور) where the text does not say."),
        "decisions_risks": ("Decisions and open issues", "القرارات والمسائل المعلقة", "Two short lists: the decisions taken, then the risks or issues left open."),
        "facts_table": ("Dates, amounts, references", "التواريخ والمبالغ والمراجع", "A Markdown table of every date, amount and reference number: Item, Value, What it refers to "
                        "(in Arabic: البند, القيمة, السياق)."),
        "minutes": ("Minutes", "محضر", "Minutes: who attended (if stated), the decisions, the action items with owner and deadline, and the next meeting."),
    },
    "length": {
        "auto": ("Decide from the request", "حسب الطلب", ""),
        "short": ("Short", "قصير", "Length: at most 60 words."),
        "medium": ("Medium", "متوسط", "Length: at most 150 words."),
        "long": ("Detailed", "مفصّل", "Length: at most 300 words."),
    },
    "audience": {
        "auto": ("Decide from the request", "حسب الطلب", ""),
        "management": ("Senior management", "الإدارة العليا", "Reader: senior management. Lead with what they must know or decide."),
        "staff": ("Staff", "الموظفون", "Reader: staff who must act on it. Lead with what they must do and by when."),
        "customer": ("A customer", "عميل", "Reader: a customer. Plain words, no internal terms."),
    },
    "language": {
        "auto": ("Language of the request", "لغة الطلب", ""),
        "ar": ("Arabic", "العربية", ""),
        "en": ("English", "الإنجليزية", ""),
    },
}
RULES = ("Summarise the text you are given, and nothing else: no outside knowledge, no opinion, no advice.\n"
         "- Keep what a reader would act on: every deadline, amount, obligation and decision, and who must do what.\n"
         "- Keep names, numbers, dates and reference codes exactly as written. Keep relations exactly too: \"from A to B\", "
         "\"before\", \"instead of\", and which person has which task.\n"
         "- Do not add a translation in brackets after a term.\n"
         "- Output only the summary: no preamble and no closing remark.")
NOTHING = {"en": "There is nothing here to summarise yet. Paste the text or attach the file, and say what form you want (for example: three key points).",
           "ar": "لا يوجد نص للتلخيص بعد. الصق النص أو أرفق الملف، واذكر الشكل المطلوب (مثلاً: ثلاث نقاط رئيسية)."}
LEGAL = re.compile(r"الطرف الأول|الطرف الثاني|الطرف الاول|المدعي|المدعى عليه|حكمت المحكمة|منطوق الحكم|هذا العقد|بموجب هذا العقد"
                   r"|hereinafter|party of the first part|\bwhereas\b|the court (finds|orders|held)|this agreement is (made|entered)", re.I)

CHECK = ("You are checking a summary against its source. For every numbered point, decide whether the source states it.\n"
         "- \"supported\": the source says this.\n"
         "- \"wrong\": the source says something different: a number or date changed, a relation turned round (from/to, "
         "before/after, increase/decrease), a task or decision given to the wrong person or body.\n"
         "- \"not_in_source\": the source does not say this at all.\n"
         "Then list, in the language of the summary, up to four specific facts from the source that a reader would need and the "
         "summary leaves out. Write each as the fact itself, with its figure or name (for example \"the daily report is due before "
         "3 pm\"), never as a kind of thing (\"a deadline\"). Return an empty list when the summary leaves out nothing of that "
         "weight, and do not list something the employee asked to leave out.")
CHECK_SCHEMA = {"type": "object", "required": ["points", "missing"], "properties": {
    "points": {"type": "array", "items": {"type": "object", "required": ["n", "verdict"], "properties": {
        "n": {"type": "integer"}, "verdict": {"type": "string", "enum": ["supported", "wrong", "not_in_source"]}, "note": {"type": "string"}}}},
    "missing": {"type": "array", "items": {"type": "string"}}}}


def options(lang: str) -> dict:
    i = 1 if lang == "ar" else 0
    return {"options": {name: [{"id": k, "label": v[i]} for k, v in choices.items()] for name, choices in OPTIONS.items()}}


def keep_missing(items: list[str], summary: str) -> list[str]:
    """Drop a "left out" remark that says nothing (a bare category) or that the summary plainly does not leave out
    (every figure it names is in the summary)."""
    text = evidence.canon(summary)
    out = []
    for m in items:
        if len(m.split()) < 4:              # "a deadline", "التزام": a kind of thing, not a fact from the source
            continue
        figs = [f for f in re.findall(r"\d+(?:\.\d+)?", evidence.canon(m)) if len(f) >= 2]
        if not (figs and all(re.search(rf"(?<![\d.]){re.escape(f)}(?!\d)", text) for f in figs)):
            out.append(m)
    return out


def context(lang: str, opts: dict | None = None) -> str:
    """The summary rules and the employee's choices, as a block for the system prompt."""
    opts = opts or {}
    lines = [OPTIONS[name][opts.get(name) or "auto"][2] for name in ("form", "length", "audience") if (opts.get(name) or "auto") in OPTIONS[name]]
    if (opts.get("focus") or "").strip():
        lines.append(f"Cover only this, and leave out the rest: {opts['focus'].strip()[:300]}")
    language = "Write the summary in Arabic (Modern Standard Arabic)" if lang == "ar" else "Write the summary in English"
    if opts.get("language") in ("ar", "en"):       # chosen on the options bar: it wins over the language of the request and of the text
        lines.append(f"{language}. The employee chose this language: use it even though the request or the text is in another language.")
    else:
        lines.append(f"{language}, whatever the language of the text, unless the request asks for another.")
    if lang == "ar":
        lines.append("In an Arabic summary, use an English word only where the text itself has it.")
    return RULES + "\n" + "\n".join(f"- {ln}" for ln in lines if ln)


def reminder(lang: str, opts: dict | None) -> str:
    """Placed after the source text when the employee chose the language: the last thing read before writing."""
    if (opts or {}).get("language") not in ("ar", "en"):
        return ""
    return "Write the summary in Arabic, although the text is in another language." if lang == "ar" else "Write the summary in English, although the text is in Arabic."


def pasted(message: str, lang: str) -> tuple[str, dict | None]:
    """A request with the text to summarise pasted after it -> (the request alone, the text as a file-like source).
    The text is cut into numbered passages, one or two sentences each, so each point of the summary can cite its own."""
    m = re.match(r"^(.{0,220}?[:：\n])\s*(.+)$", message.strip(), re.S)
    if not m or len(m.group(2).split()) < 12:          # a dozen words is already a text someone may want in one line
        return message, None
    ask, text = m.group(1).strip(" :：\n"), m.group(2).strip()
    # One sentence per block; a short one joins the next (evidence.split)
    blocks = "\n\n".join(s.strip() for line in text.split("\n") for s in re.split(r"(?<=[.!?؟])\s+", line) if s.strip())
    name = "النص الملصق" if lang == "ar" else "pasted text"
    return ask or message[:200], {"name": name, "text": text, "paged": False, "kind": "pasted", "passages": evidence.split([{"page": 1, "text": blocks}], False),
                                 "info": {"file_id": None, "converted_by": "pasted into the message", "structure": None}}


def sections(passages: list[dict]) -> list[list[dict]]:
    """Numbered passages grouped into sections of at most SECTION_CHARS, in order, never splitting a passage."""
    out, cur, size = [], [], 0
    for p in passages:
        if cur and size + len(p["prompt"]) > SECTION_CHARS:
            out.append(cur)
            cur, size = [], 0
        cur.append(p)
        size += len(p["prompt"])
    return out + ([cur] if cur else [])


def section_text(group: list[dict]) -> str:
    """One section as the model reads it: the same numbered form as a whole file, with file and page markers."""
    lines, where = [], None
    for p in group:
        here = f"{p['file']} · {p['where']}" if p["where"] else p["file"]
        if here != where:
            where = here
            lines.append(f"[{here}]")
        lines.append(f"[{p['label']}]\n{p['prompt']}" if p.get("table") and "\n" in p["prompt"] else f"[{p['label']}] {p['prompt']}")
    return "\n\n".join(lines)


def points(summary: str) -> list[str]:
    """The separate statements of a summary: list items and table rows where it has them, sentences otherwise."""
    lines = [ln.strip() for ln in summary.split("\n") if ln.strip()]
    rows = [ln for ln in lines if re.match(r"^(?:[-*•]|\d+[.)])\s+\S", ln) or (ln.startswith("|") and not re.match(r"^\|[\s:|-]+\|$", ln))]
    if len(rows) >= 2:
        return rows[1:] if rows[0].startswith("|") else rows            # a table's header row is not a statement
    return [s.strip() for s in re.split(r"(?<=[.!?؟])\s+", " ".join(lines)) if len(s.split()) > 2]


def legal(text: str) -> bool:
    """Does this read like a contract or a court ruling? Three or more of the usual markers."""
    return len(LEGAL.findall(text[:20000])) >= 3


def coverage(by_label: dict, files: list[dict], in_sections: int) -> dict:
    """What the summary was built from, in plain terms, for the line under it."""
    total = sum(len(f.get("passages") or []) for f in files)
    pages = sorted({(p["file"], p["page"]) for p in by_label.values() if p["where"].startswith(("Page", "Sheet"))})
    all_pages = sum(len(f.get("parts") or []) for f in files if f.get("paged"))
    return {"passages_read": len(by_label), "passages_total": total, "parts_read": len(pages), "parts_total": all_pages,
            "complete": len(by_label) >= total, "sections": in_sections}
