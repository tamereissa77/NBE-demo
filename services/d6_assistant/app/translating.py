"""Translation for D6, Arabic and English in both directions.

A translation is trusted when nothing was lost and nothing changed on the way, so the work is done in a form
that can be checked:
- The source is cut into segments (a paragraph, a heading, a list item, a table row) and translated segment by
  segment, a few thousand characters per model call. A long text is therefore translated to its end instead of
  stopping where one answer runs out, and the source and the translation stay aligned for a side-by-side view.
- Each segment is then read back in code: every number, date part, reference code, e-mail address and web address
  of the source must be in the translation, and no figure may appear that the source does not have. A segment
  that fails is translated once more on its own; if it still fails it is flagged for the employee.
- The bank's own terms (nbe_core.locale.GLOSSARY) are given to the model for the segments that contain them, and
  the result is checked for them.
What is not checked: wording and tone, and how a person's name is spelt in the other alphabet.

Pure Python; the model calls are made in main.py.
"""
import re

from nbe_core import locale as L

from app import evidence

BATCH_CHARS = 2500             # of source text per model call
MAX_CHARS = 40000              # of source text translated in one request; the rest is reported, never dropped in silence
MARK = re.compile(r"<<(\d+)>>")
INTO_EN = re.compile(r"للإنجليزي|للانجليزي|إلى الإنجليزي|الى الانجليزي|بالإنجليزي|بالانجليزي|(?:in)?to english|in english", re.I)
INTO_AR = re.compile(r"للعربي|إلى العربي|الى العربي|بالعربي|(?:in)?to arabic|in arabic", re.I)
ARABIC_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")

# Each choice: (English label, Arabic label, the instruction it adds)
OPTIONS = {
    "target": {"auto": ("The other language", "اللغة الأخرى", ""), "en": ("English", "الإنجليزية", ""), "ar": ("Arabic", "العربية", "")},
    "register": {
        "auto": ("As the source", "كالنص الأصلي", "Keep the register of the source."),
        "formal": ("Formal letter", "خطاب رسمي", "Register: formal correspondence, with the customary forms of address and closing in the target language."),
        "plain": ("Plain, for a customer", "مبسّط للعميل", "Register: plain words a customer understands; no internal jargon."),
        "literal": ("Close to the wording", "قريب من النص", "Stay as close to the wording and sentence order of the source as the target language allows."),
    },
    "numerals": {"western": ("123", "123", ""), "arabic_indic": ("١٢٣ (in Arabic text)", "١٢٣ (في النص العربي)", "")},
}
NOTHING = {"en": "There is nothing here to translate yet. Paste the text after your request, or attach the file.",
           "ar": "لا يوجد نص للترجمة بعد. الصق النص بعد طلبك أو أرفق الملف."}


def options(lang: str) -> dict:
    i = 1 if lang == "ar" else 0
    return {"options": {name: [{"id": k, "label": v[i]} for k, v in choices.items()] for name, choices in OPTIONS.items()}}


def request_and_text(message: str) -> tuple[str, str]:
    """A request with the text to translate after it -> (the request, the text). No text: (message, "")."""
    m = re.match(r"^(.{0,160}?[:：\n])\s*(.+)$", message.strip(), re.S)
    return (m.group(1).strip(" :：\n"), m.group(2).strip()) if m and m.group(2).strip() else (message, "")


THE_FILE = re.compile(r"\b(files?|documents?|attachments?|attached|pdf|letter|circular|whole|entire|page)\b"
                      r"|الملف|الملفات|المستند|الوثيقة|المرفق|الكتاب|الخطاب|التعميم|كامل|كله|كاملا", re.I)


def wants_file(request: str) -> bool:
    """With a file attached and an answer already given, "translate into English" means the answer just given;
    "translate this file" means the file. The request says which."""
    return bool(THE_FILE.search(request))


def target(request: str, text: str, chosen: str = "") -> str:
    """The language to translate into: the one chosen, the one the request names, or the other one from the text's."""
    if chosen in ("ar", "en"):
        return chosen
    if INTO_EN.search(request):
        return "en"
    if INTO_AR.search(request):
        return "ar"
    ar, la = len(re.findall(r"[؀-ۿ]", text)), len(re.findall(r"[A-Za-z]", text))
    return "en" if ar >= la else "ar"


def segments(text: str) -> list[dict]:
    """The text as units that are translated and checked one by one: {text, sep}. A paragraph, a heading and a table
    row are units; `sep` is what followed the unit in the source (a line break or a blank line), so the translation
    can be put back together in the same shape. File markers such as [Page 2] are layout, not text: they are dropped."""
    out: list[dict] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln for ln in block.split("\n") if ln.strip() and not re.fullmatch(r"\s*\[(?:Page \d+|Sheet: .*)\]\s*", ln)]
        listy = sum(bool(re.match(r"\s*(?:[-*•|#]|\d+[.)])", ln)) for ln in lines) >= max(1, len(lines) // 2)
        units = lines if listy or len(lines) <= 1 or all(len(ln) < 90 for ln in lines) else ["\n".join(lines)]   # short lines: an address block, a signature
        for i, u in enumerate(units):
            if re.fullmatch(r"\s*\|[\s:|-]+\|\s*", u):               # the rule under a table header: copied, not translated
                out.append({"text": u, "sep": "\n", "copy": True})
            else:
                out.append({"text": u, "sep": "\n" if i < len(units) - 1 else "\n\n"})
    return out


def batches(segs: list[dict]) -> list[list[int]]:
    """Indexes of the segments to translate, grouped into model calls of at most BATCH_CHARS."""
    out, cur, size = [], [], 0
    for i, s in enumerate(segs):
        if s.get("copy"):
            continue
        if cur and size + len(s["text"]) > BATCH_CHARS:
            out.append(cur)
            cur, size = [], 0
        cur.append(i)
        size += len(s["text"])
    return out + ([cur] if cur else [])


def terms_for(text: str, to: str) -> list[tuple[str, str]]:
    """The glossary entries whose source-language side occurs in this text: (as written in the source, as to be written)."""
    c = evidence.canon(text)
    return [(ar, en) if to == "en" else (en, ar) for ar, en in L.GLOSSARY
            if evidence.canon(ar if to == "en" else re.sub(r"\s*\(.*?\)", "", en)) in c or (to == "ar" and (m := re.search(r"\((\w+)\)", en)) and m.group(1).lower() in c.split())]


def prompt(batch: list[tuple[int, str]], to: str, opts: dict) -> str:
    language = "English" if to == "en" else "Arabic (Modern Standard Arabic)"
    terms = terms_for(" ".join(t for _, t in batch), to)
    rules = [f"Translate each numbered segment into {language}.",
             "Keep the <<n>> markers exactly as they are, one per segment, in the same order, each on its own line before its segment.",
             "Translate everything and add nothing: no notes, no explanations, no alternatives.",
             "Keep the layout inside a segment: Markdown signs (#, -, *, |), line breaks and table columns stay where they are.",
             "Copy unchanged: numbers, dates' day and year numbers, amounts, reference codes, e-mail addresses, web addresses and text in [square brackets].",
             OPTIONS["register"][opts.get("register") or "auto"][2]]
    if terms:
        rules.append("Use the bank's terms: " + "; ".join(f"{a} = {b}" for a, b in terms) + ".")
    return "\n".join(f"- {r}" for r in rules if r) + "\n\n" + "\n".join(f"<<{n}>>\n{t}" for n, t in batch)


def parse(reply: str, wanted: list[int]) -> dict[int, str]:
    """The model's reply back into segments by marker. A marker that is missing simply leaves its segment untranslated."""
    found, parts = {}, MARK.split(reply)
    for k in range(1, len(parts) - 1, 2):
        n = int(parts[k])
        if n in wanted and n not in found:
            found[n] = parts[k + 1].strip("\n ").strip()
    return found


def _figures(text: str) -> list[str]:
    """What must cross a translation unchanged: reference codes, addresses, and numbers of two or more digits."""
    t = evidence.canon(text)
    fixed = re.findall(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}|(?:https?://|www\.)[^\s|)]+", text.lower())
    codes = re.findall(r"[a-z]{1,10}(?:[-/][a-z0-9]+)*[-/]\d[a-z0-9/-]*", t)
    for c in fixed + codes:
        t = t.replace(c, " ")
    return list(dict.fromkeys([f.rstrip(".,") for f in fixed] + codes + [n for n in re.findall(r"\d+(?:\.\d+)?", t) if len(n.lstrip("0")) >= 2]))


def check(source: str, translated: str, to: str) -> dict:
    """One segment read back: {status: ok | check | empty, missing, extra, terms}."""
    if not translated.strip():
        return {"status": "empty", "missing": [], "extra": [], "terms": []}
    src, out = evidence.canon(source), evidence.canon(translated)
    low = translated.lower()
    has = lambda f, where, raw: f in raw if ("@" in f or f.startswith(("www.", "http"))) else evidence._has(f, where)  # noqa: E731
    missing = [f for f in _figures(source) if not has(f, out, low)]
    extra = [f for f in _figures(translated) if not has(f, src, source.lower())]
    # A glossary term counts as used when its main words are there (Arabic takes the article and endings: الأمر المستديم)
    stem = lambda term: [w for w in evidence.canon(re.sub(r"\(.*?\)", "", term)).split() if len(w) > 2]  # noqa: E731
    terms = [want for _, want in terms_for(source, to)
             if not all(re.sub(r"^ال", "", w) in out for w in stem(want)) and not ((m := re.search(r"\((\w+)\)", want)) and m.group(1).lower() in out)]
    return {"status": "check" if missing or extra or terms else "ok", "missing": missing, "extra": extra, "terms": terms}


def finish(text: str, to: str, opts: dict) -> str:
    """The employee's choice of numerals, applied in code: Arabic-Indic digits in Arabic text, except inside codes and addresses."""
    if to != "ar" or opts.get("numerals") != "arabic_indic":
        return text
    return re.sub(r"(?<![A-Za-z0-9@./_-])\d[\d,.:/]*(?![A-Za-z@_-])", lambda m: m.group(0).translate(ARABIC_DIGITS), text)


def assemble(segs: list[dict]) -> str:
    return "".join((s.get("target") or "") + s["sep"] for s in segs if s.get("target")).strip()
