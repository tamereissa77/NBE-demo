"""Evidence for D6 file chat: numbered passages, citations, and checks on what the answer claims.

The whole file is still given to the model (nothing is retrieved), but cut into short numbered passages:
[S1], [S2], ... The model puts the number after each fact it takes from a file. From those numbers the service
builds what the portal shows under an answer: for each cited passage, the file, the page or sheet, the text, and
whether the answer's figures really are in it.

What is checked, and what is not:
- A figure (number, date part, amount, reference code) in a sentence that cites a passage must appear in that
  passage. Digits are compared after normalising Arabic-Indic digits and thousands separators, so "17 August 2026"
  checks against "١٧ أغسطس ٢٠٢٦". A figure that is not there is reported, not hidden: it may be a slip, or a value
  the model worked out.
- Text the answer puts in quotation marks must appear word for word in the files.
- A sentence with no figures is compared by its words, and only to confirm: when most of its words are in the
  passage it is marked as matching. A paraphrase or a translation shares few words, so anything else is shown as
  not checked rather than flagged.
The checks say whether the cited passage contains what the answer states. They cannot say the answer is complete.

Pure Python; no model calls.
"""
import re
import unicodedata

PASSAGE_CHARS = 900        # a longer paragraph is cut at line or sentence ends
SMALL = 60                 # a shorter block (a heading, a salutation) joins the block after it
TABLE_ROWS = 10            # rows per passage in a long table
ROW_PASSAGES = 60          # a table up to this long gets one passage per row, so a citation points at the exact row
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
LABELS = re.compile(r"(?:\[S\d+\]\s*)+")
NOT_FIGURES = re.compile(r"(?:\b(?:pages?|p\.|files?|sheets?|rows?|annex|phase|item|section|article)|صفح[ةه]|الصفح[ةه]|ملف|الملف|بند|البند|ماد[ةه])"
                         r"\s*(?:رقم|no\.?|number)?\s*[(\[]?\s*\d+\s*[)\]]?", re.I)
QUOTED = re.compile(r"[\"“«]([^\"“”«»\n]{20,300})[\"”»]")


def canon(text: str) -> str:
    """Text reduced to what must match: Western digits, no thousands separators, no diacritics or Markdown marks,
    one form for the Arabic letters that are written several ways, lower case, single spaces."""
    text = unicodedata.normalize("NFKC", text).translate(DIGITS)      # NFKC: PDF text layers store Arabic as presentation forms
    text = re.sub(r"(?<=\d)[,٬](?=\d{3})", "", text)
    text = re.sub("[ً-ْـ]", "", text)
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي").replace("ة", "ه")
    text = re.sub("[‐-―−]", "-", text)
    text = re.sub(r"[*_`|#>«»\"“”’‘']", " ", text).replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", text).lower().strip()


# ------------------------------------------------------------------ files -> passages
def _cut(text: str) -> list[str]:
    """A long paragraph as pieces of at most PASSAGE_CHARS, cut between lines; a single line longer than that is
    cut at sentence ends. Line breaks inside a piece are kept (a list stays a list)."""
    if len(text) <= PASSAGE_CHARS:
        return [text]
    out, cur = [], ""
    for line in text.split("\n"):
        pieces, run = [], ""
        for unit in ([line] if len(line) <= PASSAGE_CHARS else re.split(r"(?<=[.!?؟。:؛])\s+", line)):
            while len(unit) > PASSAGE_CHARS:               # one unbroken run longer than a passage
                pieces.append(unit[:PASSAGE_CHARS])
                unit = unit[PASSAGE_CHARS:]
            if run and len(run) + len(unit) + 1 > PASSAGE_CHARS:
                pieces.append(run)
                run = ""
            run = f"{run} {unit}" if run else unit
        for piece in pieces + ([run] if run else []):
            if cur and len(cur) + len(piece) + 1 > PASSAGE_CHARS:
                out.append(cur)
                cur = ""
            cur = f"{cur}\n{piece}" if cur else piece
    return out + ([cur] if cur else [])


def split(parts: list[dict], paged: bool) -> list[dict]:
    """A file's parts (pages, sheets) as passages: {page, where, heading, text, prompt}. `text` is what the source
    panel shows (a table chunk repeats its header row); `prompt` is what the model reads (it does not)."""
    out: list[dict] = []
    heading = ""
    for part in parts:
        where = part.get("label") or (f"Page {part['page']}" if paged else "")
        blocks: list[tuple[str, list[str]]] = []           # ("text" | "table", lines)
        for line in part["text"].split("\n"):
            kind = "table" if line.lstrip().startswith("|") else "text"
            if not line.strip():
                blocks.append(("gap", []))
            elif blocks and blocks[-1][0] == kind:
                blocks[-1][1].append(line)
            else:
                blocks.append((kind, [line]))
        carry = ""                                          # a short block waiting to join the next one
        for kind, lines in [b for b in blocks if b[0] != "gap"]:
            if kind == "table":
                if carry:
                    out.append({"page": part["page"], "where": where, "heading": heading, "text": carry, "prompt": carry})
                    carry = ""
                head = lines[:2] if len(lines) > 1 and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[1]) else []
                rows = lines[len(head):]
                step = 1 if 0 < len(rows) <= ROW_PASSAGES else TABLE_ROWS
                for i in range(0, max(len(rows), 1), step):
                    chunk = rows[i:i + step]
                    out.append({"page": part["page"], "where": where, "heading": heading, "table": True,
                                "text": "\n".join(head + chunk), "prompt": "\n".join((head if i == 0 else []) + chunk)})
                continue
            for line in lines:                              # the last heading seen names the passages under it
                m = re.match(r"^#{1,6}\s+(.{1,120})$", line.strip())
                if m:
                    heading = m.group(1).strip()
            text = (carry + "\n" + "\n".join(lines)).strip() if carry else "\n".join(lines).strip()
            carry = ""
            if len(text) < SMALL:
                carry = text
                continue
            out += [{"page": part["page"], "where": where, "heading": heading, "text": t, "prompt": t} for t in _cut(text)]
        if carry:                                           # a short last block: it joins the passage before it, on the same page
            if out and out[-1]["page"] == part["page"] and not out[-1].get("table"):
                out[-1]["text"] += "\n" + carry
                out[-1]["prompt"] += "\n" + carry
            else:
                out.append({"page": part["page"], "where": where, "heading": heading, "text": carry, "prompt": carry})
    return out


def number(files: list[dict], budgets: list[int]) -> tuple[list[str], dict[str, dict]]:
    """Give every passage that fits its file's budget a number that is unique across the attached files.
    Returns the text of each file as the model reads it, and the passages by label."""
    texts, by_label, n = [], {}, 0
    for f, budget in zip(files, budgets):
        lines, used, where = [], 0, None
        for p in f.get("passages") or []:
            if used + len(p["prompt"]) > budget and lines:
                break
            n += 1
            label = f"S{n}"
            by_label[label] = {**p, "label": label, "file": f["name"], "file_id": (f.get("info") or {}).get("file_id"),
                               "page_image": bool(f.get("raw")) and bool(p["where"].startswith("Page") or not p["where"])}
            if p["where"] and p["where"] != where:
                where = p["where"]
                lines.append(f"[{where}]")
            # A number on its own line belongs to the lines under it (a table header, or several rows)
            lines.append(f"[{label}]\n{p['prompt']}" if p.get("table") and "\n" in p["prompt"] else f"[{label}] {p['prompt']}")
            used += len(p["prompt"])
        texts.append("\n\n".join(lines))
    return texts, by_label


# ------------------------------------------------------------------ answer -> citations and checks
def tidy(answer: str, by_label: dict) -> str:
    """Citation marks in one form. Models write them many ways: [S1, S3], 【S2】, [ S2 ], [file.xlsx:S2], [S4]-[S6],
    [س4] (the Arabic letter). All become "[S1][S3]"; a number that was never given is removed."""
    answer = re.sub("[\u200b\u200c\u200d\u2060\ufeff]", "", answer)
    answer = answer.replace("【", "[").replace("】", "]")
    dash = "[-\u2010-\u2015]"
    answer = re.sub(rf"\[\s*[Sس]\s*(\d+)\s*\]\s*{dash}\s*\[\s*[Sس]\s*(\d+)\s*\]", r"[S\1-S\2]", answer)          # [S4]-[S6]

    def marks(m: re.Match) -> str:
        inside = m.group(1)
        labels: list[str] = []
        for lo, hi in re.findall(rf"[Sس]\s*(\d+)(?:\s*{dash}\s*[Sس]?\s*(\d+))?", inside):
            last = int(hi) if hi and 0 < int(hi) - int(lo) <= 12 else int(lo)                      # a short range is spelled out
            labels += [f"S{n}" for n in range(int(lo), last + 1)]
        rest = re.sub(rf"[Sس]\s*\d+|{dash}", " ", inside).strip(" ,،;:و&")
        rest = f"({rest}) " if re.search(r"\w{3,}", rest) else ""                                    # e.g. a file name written with the number
        return rest + "".join(f"[{s}]" for s in dict.fromkeys(labels))

    answer = re.sub(r"\[([^\[\]\n]{0,80}?(?<![A-Za-z])[Sس]\s*\d+[^\[\]\n]{0,80}?)\]", marks, answer)
    answer = re.sub(r"\((S\d+)\)", r"[\1]", answer)
    return re.sub(r"\s*\[(S\d+)\]", lambda m: m.group(0) if m.group(1) in by_label else "", answer)


def _figures(claim: str) -> list[str]:
    """The checkable tokens of a sentence: reference codes and numbers (dates and times piece by piece)."""
    claim = re.sub(r"\S+\.(?:pdf|docx|pptx|xlsx|xlsm|csv|tsv|md|txt|html?|png|jpe?g|webp)\b", " ", claim, flags=re.I)   # a file name is not a claim
    text = canon(NOT_FIGURES.sub(" ", re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", claim)))
    codes = re.findall(r"[a-z]{1,10}(?:[-/][a-z0-9]+)*[-/]\d[a-z0-9/-]*", text)             # L-1017, aml/cft-circ/2026/09
    rest = text
    for c in codes:
        rest = rest.replace(c, " ")
    numbers = [n for n in re.findall(r"\d+(?:\.\d+)?", rest) if len(n) >= 2]                # a lone digit proves nothing
    return list(dict.fromkeys(codes + numbers))


_UNITS_AR = ["", "واحد", "اثن", "ثلاث", "اربع", "خمس", "ست", "سبع", "ثمان", "تسع"]       # stems, after canon(): the endings vary
_TENS_AR = ["", "عشر", "عشر", "ثلاث", "اربع", "خمس", "ست", "سبع", "ثمان", "تسع"]
_UNITS_EN = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
             "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS_EN = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _in_words(n: int) -> str:
    """A pattern for 2..99 written out, in Arabic or English ("خمسة عشر يوماً", "fifteen days"), to match canonical text."""
    en = _UNITS_EN[n] if n < 20 else _TENS_EN[n // 10] + (f"[ -]{_UNITS_EN[n % 10]}" if n % 10 else "")
    w = r"[\u0621-\u064a]*"                                 # the rest of an Arabic word: ة / ا / ون / ين ...
    if n <= 10:
        ar = ("عشر" if n == 10 else _UNITS_AR[n]) + w
    elif n < 20:
        ar = ("احد" if n == 11 else _UNITS_AR[n - 10]) + w + r"\s+عشر" + w
    else:
        tens = ("عشر" if n // 10 == 2 else _TENS_AR[n // 10]) + r"(?:ون|ين)"
        ar = (_UNITS_AR[n % 10] + w + r"\s+و\s*" if n % 10 else "") + tens
    return rf"(?<![a-z\u0621-\u064a])(?:{en}|{ar})(?![a-z\u0621-\u064a])"


def _has(fig: str, text: str) -> bool:
    """Is the figure in the (canonical) text as a whole number? "25" is not in "25945221". A number from 2 to 99 also
    counts when the text spells it out, as contracts and formal letters do."""
    if not fig[0].isdigit():
        return fig in text
    if re.search(rf"(?<![\d.]){re.escape(fig)}(?!\d|\.\d)", text):
        return True
    return fig.isdigit() and 2 <= int(fig) <= 99 and re.search(_in_words(int(fig)), text) is not None


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{4,}|[ء-ي]{4,}", canon(text)))


def _closest(claim: str, passage: str) -> str:
    """The line of the passage that shares most with the claim: what the panel highlights."""
    figs, words = _figures(claim), _words(claim)
    lines = [ln for ln in re.split(r"\n|(?<=[.!?؟])\s+", passage) if ln.strip() and not re.match(r"^\s*\|[\s:|-]+\|\s*$", ln)]
    def shared(ln: str) -> float:
        c = canon(ln)
        return 3 * sum(_has(f, c) for f in figs) + len(words & _words(ln))
    best = max(lines, key=shared, default="")
    return best.strip()[:400] if best and shared(best) > 0 else ""


def verify(answer: str, by_label: dict) -> list[dict]:
    """The passages the answer cites, in order of first use, each with the result of checking the sentences that cite it."""
    found: dict[str, dict] = {}
    for line in answer.split("\n"):
        end = 0
        for m in LABELS.finditer(line):
            claim = LABELS.sub(" ", line[end:m.start()]).strip()
            if len(claim) < 12:                             # the marks came after a fragment: judge the whole line
                claim = LABELS.sub(" ", line).strip()
            end = m.end()
            cited = [s for s in re.findall(r"S\d+", m.group(0)) if s in by_label]
            if not cited:
                continue
            together = canon(" ".join(by_label[s]["text"] for s in cited))
            figs = _figures(claim)
            missing = [f for f in figs if not _has(f, together)]
            # A figure that is in another passage of the files: the citation points at the wrong place, the figure is real
            elsewhere = {f: [lab for lab, p in by_label.items() if _has(f, canon(p["text"]))][:3] for f in missing}
            # "... on page 4 [S13]" when S13 is on page 3: the sentence contradicts its own citation
            said = {int(n) for n in re.findall(r"(?:pages?|صفح[ةه]|الصفح[ةه])\s*(?:رقم\s*)?[(\[]?\s*(\d+)", canon(claim))}
            on = {by_label[s]["page"] for s in cited if by_label[s]["where"].startswith("Page")}
            wrong_page = sorted(said - on) if said and on and not (said & on) else []
            # Flagged: a figure that is nowhere in the cited file, or a page that contradicts the citation. A figure that
            # is in another passage of the same file (the year from the title, the row next door) is real: noted, not flagged.
            same_file = {lab for lab, p in by_label.items() if p["file"] in {by_label[s]["file"] for s in cited}}
            nowhere = [f for f in missing if not set(elsewhere[f]) & same_file]
            if wrong_page or nowhere:
                status = "check"
            elif figs:
                status = "nearby" if missing else "verified"
            else:
                # No figures to compare: go by the words, and only ever to confirm. Different wording, a translation
                # or a paraphrase is not evidence of a wrong citation, so a low overlap is "not checked", never a flag.
                mine, theirs = _words(claim), _words(together)
                status = "supported" if len(mine) >= 3 and len(mine & theirs) >= 0.5 * len(mine) else "unchecked"
            for s in cited:
                src = found.setdefault(s, {k: by_label[s][k] for k in ("label", "file", "file_id", "page", "where", "heading", "text", "page_image")}
                                       | {"status": status, "missing": [], "elsewhere": {}, "wrong_page": [], "snippet": ""})
                rank = ["verified", "supported", "nearby", "unchecked", "check"]
                if rank.index(status) > rank.index(src["status"]):
                    src["status"] = status
                src["missing"] = list(dict.fromkeys(src["missing"] + missing))
                src["elsewhere"].update({f: labs for f, labs in elsewhere.items() if labs})
                src["wrong_page"] = sorted(set(src["wrong_page"]) | set(wrong_page))
                src["snippet"] = src["snippet"] or _closest(claim, by_label[s]["text"])
    return list(found.values())


def loose_figures(answer: str, by_label: dict) -> list[str]:
    """Figures the answer states that appear nowhere in the files, cited or not. Each is either a value the model
    worked out (a difference, a count) or one it got wrong; the reader is told which figures to look at."""
    everything = canon(" ".join(p["text"] for p in by_label.values()))
    out = []
    for line in answer.split("\n"):
        out += [f for f in _figures(LABELS.sub(" ", line)) if not _has(f, everything)]
    return list(dict.fromkeys(out))


def attribute(text: str, by_label: dict, limit: int = 8) -> list[dict]:
    """Sources for a text that carries no citation marks (a drafted letter): for each line that states figures, the
    passage that contains them. Found by the figures themselves, so every source listed does contain them."""
    canon_text = {label: canon(p["text"]) for label, p in by_label.items()}
    found: dict[str, dict] = {}
    for line in text.split("\n"):
        figs = _figures(line)
        if not figs:
            continue
        hits = {label: [f for f in figs if _has(f, t)] for label, t in canon_text.items()}
        label = max(hits, key=lambda k: (len(hits[k]), len(_words(line) & _words(by_label[k]["text"]))), default=None)
        if not label or not hits[label]:
            continue
        missing = [f for f in figs if f not in hits[label]]
        src = found.setdefault(label, {k: by_label[label][k] for k in ("label", "file", "file_id", "page", "where", "heading", "text", "page_image")}
                               | {"status": "verified", "missing": [], "elsewhere": {}, "wrong_page": [], "snippet": _closest(line, by_label[label]["text"])})
        if missing:
            src["status"] = "nearby"
            src["missing"] = list(dict.fromkeys(src["missing"] + missing))
        if len(found) >= limit:
            break
    return list(found.values())


def quotes(answer: str, by_label: dict) -> list[dict]:
    """Every passage the answer puts in quotation marks, and whether those words are in the files as written."""
    out = []
    texts = {label: canon(p["text"]) for label, p in by_label.items()}
    everything = " ".join(texts.values())
    for q in dict.fromkeys(m.group(1).strip() for m in QUOTED.finditer(LABELS.sub(" ", answer))):
        c = canon(q).rstrip(".…")
        if len(c.split()) < 3:
            continue
        label = next((s for s, t in texts.items() if c in t), None)
        out.append({"quote": q, "found": bool(label) or c in everything, "label": label})
    return out


def summary(sources: list[dict], quoted: list[dict], loose: list[str]) -> dict:
    count = lambda st: sum(s["status"] == st for s in sources)  # noqa: E731
    return {"figures_not_in_files": loose, "cited": len(sources), "verified": count("verified") + count("supported") + count("nearby"), "to_check": count("check"),
            "unchecked": count("unchecked"), "quotes": len(quoted), "quotes_not_found": sum(not q["found"] for q in quoted)}
