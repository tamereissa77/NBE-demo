"""D5 · Legal Documents Summarisation (PLAN.md §4 D5).

Legal uploads (or picks) a ruling or contract and gets: a structured summary (chunked map-reduce,
not one huge context), extracted clauses with verbatim quotes, risk flags, and a clause-by-clause
comparison against NBE's approved template.

Model: the Arabic gate's provisional result drops Gemma 4 31B, so the reduce step uses the alias in
D5_REDUCE_ALIAS (default workhorse). Setting it to `quality` uses the 31B when that profile is up;
the gateway falls back to the workhorse otherwise.
"""
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import File, HTTPException, UploadFile
from pydantic import BaseModel

from nbe_core import create_app, llm, platform, retrieval
from nbe_core.text import normalize_ar
from nbe_core.trace import Trace

SEED = Path(os.getenv("D5_SEED_DIR", "/data/seed/d5"))
REDUCE_ALIAS = os.getenv("D5_REDUCE_ALIAS", "workhorse")   # "quality" = Gemma 4 31B (falls back to workhorse)
COLLECTION = "d5_legal"
app = create_app("d5", "Legal Documents Summarization", phase="wave1")
CACHE: dict[str, dict] = {}

CLAUSE_TYPES = {
    "governing_law": "القانون أو النظام الواجب التطبيق والاختصاص القضائي أو اللجان المختصة أو التحكيم",
    "late_payment": "التأخر في السداد والإنذار أو الإشعار والغرامات وحلول الأقساط",
    "prepayment": "السداد المعجل أو المبكر وتكلفته",
    "rate": "العائد أو الفائدة أو معدل الربح وتعديله",
    "termination": "إنهاء العقد",
    "liability": "حدود المسؤولية والتعويض",
    "insurance": "التأمين أو التأمين التكافلي",
    "data": "سرية البيانات ومشاركتها",
    "security": "الضمانات",
}


def is_english(text: str) -> bool:
    """English documents (test copies in data/seed/d5_en) get English output; Arabic stays the default."""
    return len(re.findall(r"[A-Za-z]", text)) > len(re.findall(r"[؀-ۿ]", text))


def split_clauses(md: str) -> list[dict]:
    """Contracts: one chunk per article (المادة N). Rulings: one chunk per ## section."""
    parts = re.split(r"\n(?=(?:#+\s*)?\**(?:المادة|Article)\s+\d+)", md)
    if len(parts) > 2:
        out = []
        for p in parts:
            m = re.match(r"(?:#+\s*)?\**(?:المادة|Article)\s+(\d+)\s*[-–:]?\s*([^\n*]*)", p.strip())
            if m:
                out.append({"no": int(m.group(1)), "title": m.group(2).strip(" *"), "text": p.strip()})
        if out:
            return out
    out = []
    for i, block in enumerate(re.split(r"\n(?=## )", md)):
        title = block.strip().splitlines()[0].lstrip("# ").strip() if block.strip() else f"جزء {i}"
        if block.strip():
            out.append({"no": i, "title": title, "text": block.strip()})
    return out


def manifest() -> dict:
    p = SEED / "manifest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"contracts": [], "rulings": []}


@app.get("/documents")
def documents():
    m = manifest()
    docs = [{"file": "template.md", "kind": "template", "title": "نموذج عقد التمويل الشخصي المعتمد"}]
    docs += [{"file": c["file"], "kind": "contract", "title": f"عقد {c['file'][:3]} - {c['borrower']}"} for c in m["contracts"]]
    docs += [{"file": r["file"], "kind": "ruling", "title": f"{r['id']} - {r['topic']}"} for r in m["rulings"]]
    return docs


@app.get("/doc/{file}")
def doc(file: str):
    path = SEED / Path(file).name
    if not path.exists():
        raise HTTPException(404, "unknown document")
    return {"file": file, "text": path.read_text(encoding="utf-8")}


@app.post("/admin/ingest")
async def ingest():
    """Index all clauses so the shared RAG pipeline can answer questions across the legal corpus."""
    await retrieval.ensure_collection(COLLECTION, recreate=True)
    texts, payloads = [], []
    for d in documents():
        for c in split_clauses((SEED / d["file"]).read_text(encoding="utf-8")):
            texts.append(c["text"])
            payloads.append({"file": d["file"], "kind": d["kind"], "title": d["title"], "clause_no": c["no"], "clause_title": c["title"]})
    n = await retrieval.upsert(COLLECTION, texts, payloads)
    CACHE.clear()
    return {"ingested_chunks": n}


SEVERITY = {"type": "string", "enum": ["low", "medium", "high"]}
SUMMARY_SCHEMA = {"type": "object", "properties": {
    "document_type": {"type": "string"}, "parties": {"type": "array", "items": {"type": "string"}},
    "key_points": {"type": "array", "items": {"type": "string"}, "maxItems": 7},
    "outcome_or_obligations": {"type": "string"}, "amounts": {"type": "array", "items": {"type": "string"}},
    # Added fields, all optional so older clients keep working. article_refs is recomputed from the
    # key_point prefixes; court/outcome/award_split are rulings only and null for contracts.
    "article_refs": {"type": "array", "items": {"type": "integer"}},
    "court": {"type": "string"}, "outcome": {"type": "string"},
    # party = who BEARS the amount (pays it or carries that share of the loss); beneficiary = who gets it.
    # "party" alone was ambiguous and the model named the plaintiff for both halves of R02's split.
    "award_split": {"type": "array", "items": {"type": "object", "properties": {
        "party": {"type": "string"}, "role": {"type": "string", "enum": ["pays", "bears_loss"]},
        "beneficiary": {"type": "string"}, "amount": {"type": "string"}, "share": {"type": "string"}},
        "required": ["party", "role", "amount", "share"]}},
    },
    "required": ["document_type", "parties", "key_points", "outcome_or_obligations", "amounts"]}
# summary["compound_risks"] ({articles, severity, risk, theme}) is computed in code after the template diff
# (compound_risks below), so the model is not asked for it.

# Protection themes over the template's article numbers. A compound risk fires when two or more articles
# of one theme deviate in the same contract: each change is worse together than alone.
THEMES = {
    "cost_of_credit": ({3, 5, 6}, "تكلفة التمويل على المقترض", "Cost of credit to the borrower"),
    "default_and_exit": ({6, 8, 9}, "التعثر والإنهاء وحقوق المقترض فيهما", "Default, termination and the borrower's rights in them"),
    "recourse": ({10, 12}, "حق المقترض في التعويض واللجوء إلى القضاء", "The borrower's recourse and forum"),
}

# Fixed rubric so severity is the same from run to run (matches the planted severities in manifest.json)
SEVERITY_RUBRIC = (
    "مقياس الخطورة الثابت: "
    "high = إلغاء أو تقييد حق للمقترض أو إجراء إخطار/إنذار (مهلة التأخر، الإنذار، حق السداد المعجل، الإخطار قبل تعديل العائد)، "
    "أو تغيير القانون الواجب التطبيق أو جهة الاختصاص أو التحكيم؛ "
    "medium = تغيير في مقدار عمولة أو غرامة فقط، أو أي تغيير في مواد التأمين أو حدود مسؤولية البنك أو سرية ومشاركة البيانات "
    "حتى لو أُلغي التأمين الإلزامي أو حُذف استثناء الغش أو سُمح بمشاركة البيانات (هذه المواد medium دائماً ما لم تُحذف المادة كلها)؛ "
    "low = تغيير في الصياغة فقط دون أثر على الحقوق أو المبالغ. "
    "إذا اجتمع أكثر من تغيير فالخطورة هي أعلاها.")
SEVERITY_RUBRIC_EN = (
    "Fixed severity scale: high = removing or restricting a borrower right or a notice step (late-payment cure period, "
    "notice, the right to prepay, notice before a rate change), or changing the governing law, jurisdiction or "
    "arbitration; medium = only the size of a fee or penalty changed, or any change to insurance, the bank's liability "
    "or data confidentiality and sharing, even if mandatory insurance or the fraud exception is removed or data sharing "
    "is allowed (these are always medium unless the whole article is deleted); low = wording only, with no effect on "
    "rights or amounts. If several changes apply, the severity is the highest of them.")
# Insurance (7), liability (10) and data (11) are medium whatever changed, unless the article is deleted
# (status "missing", always high). Enforced in code because Gemma does not always follow the rubric here.
MEDIUM_ARTICLES = {7, 10, 11}

CLAUSE_SCHEMA = {"type": "object", "properties": {"clauses": {"type": "array", "items": {"type": "object", "properties": {
    "type": {"type": "string", "enum": list(CLAUSE_TYPES)}, "article": {"type": "integer"},
    "summary": {"type": "string"}, "quote": {"type": "string"}}, "required": ["type", "article", "summary", "quote"]}}},
    "required": ["clauses"]}

DIFF_SCHEMA = {"type": "object", "properties": {
    "deviates": {"type": "boolean"}, "severity": {"type": "string", "enum": ["none", "low", "medium", "high"]},
    # Structured, not "a ← b" strings: arrows are ambiguous in right-to-left text and the model reversed them
    "changes": {"type": "array", "items": {"type": "object", "properties": {
        "aspect": {"type": "string"}, "template": {"type": "string"}, "contract": {"type": "string"}},
        "required": ["aspect", "template", "contract"]}}, "risk": {"type": "string"}},
    "required": ["deviates", "severity", "changes", "risk"]}


async def analyze_text(name: str, text: str, kind: str) -> dict:
    trace = Trace()
    en = is_english(text)
    out = "باللغة الإنجليزية" if en else "بالعربية"      # output language follows the document
    chunks = split_clauses(text)
    trace.add("chunk", f"Split into {len(chunks)} parts", [c["title"] for c in chunks])

    # Map: summarise each part in parallel (fast workhorse)
    async def map_one(c):
        # A gateway failure (timeout, 5xx) gets one more try; after that the part's own opening text stands in
        # for its summary, so one stalled call does not fail the whole document
        for attempt in range(2):
            try:
                return c, await _map_call(c)
            except httpx.HTTPError:
                if attempt == 1:
                    return c, _TextResult(re.sub(r"\s+", " ", c["text"])[:300])

    async def _map_call(c):
        return await llm.chat([{"role": "user", "content":
            f"لخّص هذا الجزء من وثيقة قانونية في جملتين إلى ثلاث جمل {out}. انقل كل رقم ومبلغ ونسبة ومدة حرفياً كما وردت في النص دون تقريب أو حذف. "
            "إن كان الجزء هو المنطوق فاذكر المبلغ المحكوم به فعلاً وأي نسب لتوزيع المسؤولية أو الضرر بين الأطراف.\n\n"
            f"{c['text']}"}],
            max_tokens=300, temperature=0)
    mapped = await asyncio.gather(*(map_one(c) for c in chunks))
    trace.add("llm", f"Map: summarise {len(chunks)} parts in parallel (workhorse)",
              {"parts": len(chunks), "tokens": sum(r.completion_tokens for _, r in mapped)},
              max(r.latency_ms for _, r in mapped))
    ruling = kind == "ruling"
    tag = (lambda c: f"[{c['title']}]") if ruling else (lambda c: f"[{'Art.' if en else 'م.'}{c['no']}]")
    partials = "\n".join(f"- {tag(c)} ({c['title']}) {r.text.strip()}" for c, r in mapped)

    # Reduce: one structured summary from the partial summaries. Each key point keeps the source tag of the
    # part it came from. A ruling gets its operative part verbatim, because the headline amount must be the
    # one awarded there, not the one the plaintiff claimed.
    operative = _operative_part(chunks) if ruling else ""
    prompt = (f"من ملخصات الأجزاء التالية لوثيقة قانونية، اكتب ملخصاً منظماً {out} لموظف الشؤون القانونية: نوع الوثيقة، الأطراف، "
              "أهم النقاط (5 إلى 7)، المنطوق أو الالتزامات الرئيسية، والمبالغ المذكورة كما هي. "
              "ابدأ كل نقطة من أهم النقاط بوسم الجزء الذي جاءت منه كما هو بين قوسين مربعين (مثل "
              f"{'[Art.6]' if en else '[م.6]'}).")
    if ruling:
        prompt += (" هذه الوثيقة حكم: املأ court باسم المحكمة، وoutcome بنتيجة الحكم في جملة، "
                   "وaward_split بتوزيع المبالغ كما في المنطوق إن وُجد توزيع: لكل مبلغ في المنطوق، party هو الطرف الذي يتحمّل المبلغ "
                   "(الملزَم بدفعه role=pays، أو من يتحمّل تلك الحصة من الضرر بنفسه role=bears_loss)، وbeneficiary هو من يستفيد منه، "
                   "ثم المبلغ والنسبة. مثال: إلزام البنك بأن يؤدي للمدعي 60% وتحميل المدعي 40% يعني: "
                   "{party: البنك، role: pays، beneficiary: المدعي، share: 60%} و{party: المدعي، role: bears_loss، share: 40%}. "
                   "المبلغ الرئيسي هو المبلغ المحكوم به في المنطوق، وليس المبلغ المطلوب في طلبات المدعي. "
                   "ابدأ قائمة المبالغ بالمبلغ أو المبالغ الواردة في المنطوق، ولا تضع في القائمة إلا مبالغ بأرقام."
                   f"\n\nترويسة الحكم كما هي (اسم المحكمة منها):\n{text.split(chr(10) + '## ')[0].strip()}"
                   + (f"\n\nنص المنطوق كما هو:\n{operative}" if operative else ""))
    summary, res = await chat_json_d5([{"role": "user", "content": prompt + "\n\nملخصات الأجزاء:\n" + partials}],
                                      SUMMARY_SCHEMA, alias=REDUCE_ALIAS, max_tokens=1600, temperature=0)
    units = _source_units(text)
    if res:
        trace.llm(f"Reduce: structured summary ({REDUCE_ALIAS})", res)
    else:
        trace.add("llm", f"Reduce ({REDUCE_ALIAS}): malformed output " +
                  ("repaired" if summary else "unusable, built from the part summaries"), None)
        summary = summary or _fallback_summary(chunks, mapped, text, operative, units, en)
    summary.pop("_filled", None)
    # Units come from the source, not the model's echo; dedup in order; an "amount" without a number
    # ("not available") is not an amount
    amounts = [_with_unit(a.strip(), units) for a in summary["amounts"] if _numbers(a)]
    # A number with no unit, percent sign or wording is a list marker or a count the model picked up, not an amount
    amounts = [a for a in amounts if not re.fullmatch(r"[\d,.\s]+", a.translate(_DIGITS))]
    if ruling and not amounts:
        # The model sometimes returns an empty list; the operative part's own amounts are the answer then
        amounts = _operative_amounts(operative, units)
    summary["amounts"] = _order_amounts(list(dict.fromkeys(amounts)), operative)
    if not ruling:
        summary["key_points"] = [_canonical_tag(k, en) for k in summary["key_points"]]
    summary["article_refs"] = _article_refs(summary["key_points"])
    for f in ("court", "outcome", "award_split"):
        summary[f] = (summary.get(f) or None) if ruling else None
    if ruling:
        # The court is written on the header line; read it rather than trust the model to copy it
        summary["court"] = _court_from_header(text) or summary["court"]
        summary["outcome"] = (summary["outcome"] or summary.get("outcome_or_obligations")
                              or _outcome_from_operative(operative) or None)
        summary["award_split"] = _check_split(summary["award_split"], operative, units)
    summary["compound_risks"] = []

    result = {"name": name, "kind": kind, "summary": summary, "clauses": [], "diff": [], "risk_flags": [],
              "analyzed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if ruling:
        result["risk_flags"] = _unsupported_amounts(summary["amounts"], text, en)
        if result["risk_flags"]:
            trace.add("check", f"Amount self-check: {len(result['risk_flags'])} amount(s) not found in the source",
                      [f["changes"][0]["contract"] for f in result["risk_flags"]])
    if kind in ("contract", "template", "upload"):
        clauses, res = await chat_json_d5([{"role": "user", "content":
            "استخرج من العقد التالي البنود من الأنواع المحددة فقط إن وُجدت. لكل بند: النوع، رقم المادة، ملخص بجملة، واقتباس حرفي قصير من النص يثبت البند. "
            f"اكتب الملخص {out}، والاقتباس بلغة العقد كما هو.\n"
            "الأنواع: " + "؛ ".join(f"{k} = {v}" for k, v in CLAUSE_TYPES.items()) + f"\n\nالعقد:\n{text}"}],
            CLAUSE_SCHEMA, max_tokens=2500, temperature=0)
        if res:
            trace.llm("Schema-guided clause extraction (workhorse)", res)
        else:
            trace.add("llm", "Clause extraction: malformed output " + ("repaired" if clauses else "unusable, no clauses"), None)
        clauses = clauses or {"clauses": []}
        clauses.pop("_filled", None)
        # A truncated reply can end inside a clause; keep only complete ones
        need = CLAUSE_SCHEMA["properties"]["clauses"]["items"]["required"]
        clauses["clauses"] = [c for c in clauses["clauses"] if isinstance(c, dict) and all(k in c for k in need)]
        # Every clause is kept; a quote that does not occur in the document gets quote_verified=false and
        # the UI marks it. Both sides are normalised so diacritics and alef/ya/ta-marbuta forms don't matter.
        flat = _norm_quote(text)
        for c in clauses["clauses"]:
            q = _norm_quote(c["quote"])
            c["quote_verified"] = bool(q) and q in flat
        result["clauses"] = clauses["clauses"]
        if kind != "template":
            result["diff"], result["risk_flags"] = await template_diff(chunks, trace, en)
            summary["compound_risks"] = compound_risks(result["diff"], en)
            result["risk_flags"] += _compound_flags(summary["compound_risks"], en)
    result["trace"] = trace.to_list()
    result["total_ms"] = trace.total_ms()
    return result


_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٬٫", "0123456789,.")


def _norm_quote(s: str) -> str:
    return normalize_ar(re.sub(r"\s+", " ", s).strip(" .\"«»“”"))


def _numbers(s: str) -> list[str]:
    """Numbers in a text with Arabic-Indic digits converted and thousands separators removed."""
    return [n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,.]*", s.translate(_DIGITS))]


def _operative_part(chunks: list[dict]) -> str:
    """The ruling's operative section (المنطوق / Operative Part), verbatim."""
    for c in chunks:
        if re.search(r"المنطوق|Operative Part", c["title"]):
            return c["text"]
    return ""


def _order_amounts(amounts: list[str], operative: str) -> list[str]:
    """Rulings: amounts that appear in the operative part come first, so the awarded amount is the headline."""
    if not operative:
        return amounts
    awarded = set(_numbers(operative))
    return sorted(amounts, key=lambda a: not (set(_numbers(a)) & awarded))


def _canonical_tag(point: str, en: bool) -> str:
    """A contract key point's article tag in the one form the UI and article_refs read: [م.N] or [Art.N].
    The 26B on vLLM wrote the Arabic tag with a Latin letter once ("[m.7]")."""
    return re.sub(r"^\s*\[\s*(?:م|m|المادة|Art(?:icle)?)\s*\.?\s*(\d+)\s*\]",
                  lambda m: f"[{'Art.' if en else 'م.'}{m.group(1)}]", point, count=1, flags=re.I)


def _article_refs(key_points: list[str]) -> list[int]:
    """Article numbers cited by the [م.N] / [Art.N] prefixes, in order of first mention."""
    refs = re.findall(r"\[\s*(?:م\.?|Art\.?)\s*(\d+)\s*\]", " ".join(key_points))
    return list(dict.fromkeys(int(n) for n in refs))


def compound_risks(diff: list[dict], en: bool) -> list[dict]:
    """Deterministic: which articles deviate decides whether a theme fires and which articles it links.
    The prose reuses the per-article risk the comparison step wrote; severity is the highest member's."""
    rows = {r["article"]: r for r in diff if r["status"] in ("deviates", "missing")}
    order = {"low": 0, "medium": 1, "high": 2}
    out = []
    for theme, (articles, label_ar, label_en) in THEMES.items():
        hit = sorted(articles & rows.keys())
        if len(hit) < 2:
            continue
        severity = max((rows[a]["severity"] for a in hit), key=lambda s: order.get(s, 0))
        parts = "; ".join(f"{'Art.' if en else 'م.'}{a}: {rows[a]['risk'] or rows[a]['title']}" for a in hit)
        out.append({"articles": hit, "severity": severity, "theme": theme,
                    "risk": f"{label_en if en else label_ar} — {parts}"})
    return out


_UNIT = r"(جنيه(?:اً|ا)?(?:\s+مصري)?|EGP|Egyptian pounds?)"


def _source_units(text: str) -> dict[str, str]:
    """Number (digits only) -> the longest currency unit written next to it in the source."""
    src = text.translate(_DIGITS)
    found: dict[str, str] = {}
    for m in re.finditer(r"(\d[\d,.]*)\s*" + _UNIT + r"|EGP\s*(\d[\d,.]*)", src):
        num, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), "EGP")
        key = num.replace(",", "").rstrip(".")
        if len(unit) > len(found.get(key, "")):
            found[key] = re.sub(r"\s+", " ", unit)
    return found


def _with_unit(amount: str, units: dict[str, str]) -> str:
    """Rewrite the amount's number and unit with the unit the source writes next to that number
    ("47,300" or "47,300 جنيه" -> "47,300 جنيه مصري"); any other wording in the amount is kept."""
    nums = _numbers(amount)
    if len(nums) != 1 or nums[0] not in units:
        return amount
    unit = units[nums[0]]
    s = amount.translate(_DIGITS)
    s = re.sub(r"(?:EGP\s*)?(\d[\d,.]*\d)(?:\s*" + _UNIT + ")?",
               lambda m: f"EGP {m.group(1)}" if unit == "EGP" else f"{m.group(1)} {unit}", s, count=1)
    return re.sub(r"\s+", " ", s).strip()


class _TextResult:
    """Stands in for an LLMResult when a map call failed: the part's own text, no tokens, no latency."""
    def __init__(self, text: str):
        self.text, self.completion_tokens, self.latency_ms = text, 0, 0


_EMPTY = {"string": "", "array": [], "boolean": False, "integer": 0, "object": {}}


def repair_json(raw: str, schema: dict) -> dict | None:
    """Close a JSON object the model stopped writing part-way (seen with Gemma 4 on OpenRouter: the text is
    a valid prefix, e.g. '{"deviates": false, "severity": "none", "changes": []' and then nothing), then
    give missing required fields an empty value. None if the text is not such a prefix."""
    text = raw.strip().removeprefix("```json").removesuffix("```").strip()
    stack, in_str, esc = [], False, False
    for ch in text:
        if in_str:
            esc, in_str = (False, in_str) if esc else (ch == "\\", ch != '"')
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    text = (text + '"' if in_str else text).rstrip().rstrip(",")
    if text.endswith(":"):
        text += " null"
    try:
        obj = json.loads(text + "".join(reversed(stack)))
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    filled = []
    for key in schema.get("required", []):
        if obj.get(key) is None:
            obj[key] = _EMPTY.get(schema["properties"][key].get("type"), None)
            filled.append(key)
    obj["_filled"] = filled           # callers must not trust a decision field the repair invented
    return obj


async def chat_json_d5(messages: list[dict], schema: dict, **kw) -> tuple[dict | None, llm.LLMResult | None]:
    """llm.chat_json plus, in D5 only: one more round, then a repair of a truncated reply.
    Returns (None, None) when the output cannot be used or the gateway call fails (timeout, 5xx);
    the caller decides the fallback, so one bad call never fails the whole document."""
    # Calls llm.chat directly (not llm.chat_json) so a reply is repaired before any retry: Gemma 4 on
    # OpenRouter writes the JSON and then pads with whitespace up to max_tokens, so the text is a valid prefix.
    # Retrying that (chat_json's resample, then this loop) cost four ~100 s calls per article on E01.
    alias = kw.pop("alias", "workhorse")
    kw.pop("temperature", None)
    for _ in range(2):
        try:
            res = await llm.chat(messages, alias, json_schema=schema, temperature=0, **kw)
        except httpx.HTTPError:
            continue
        text = res.text.strip().removeprefix("```json").removesuffix("```").strip()
        try:
            return json.loads(text), res
        except json.JSONDecodeError:
            fixed = repair_json(text, schema)
            if fixed is not None:
                return fixed, res
    return None, None


def _fallback_summary(chunks: list[dict], mapped: list, text: str, operative: str, units: dict, en: bool) -> dict:
    """Used only when the reduce step's output is unusable: the per-part summaries, tagged, stand in."""
    ruling = bool(operative)
    tag = (lambda c: f"[{c['title']}]") if ruling else (lambda c: f"[{'Art.' if en else 'م.'}{c['no']}]")
    return {"document_type": ("Ruling" if en else "حكم") if ruling else ("Contract" if en else "عقد"),
            "parties": [], "key_points": [f"{tag(c)} {r.text.strip()}" for c, r in mapped][:7],
            "outcome_or_obligations": "", "amounts": _operative_amounts(operative, units) if ruling else []}


def _court_from_header(text: str) -> str | None:
    """'المحكمة: …' / 'Court: …' line before the first section."""
    m = re.search(r"^\s*(?:المحكمة|Court)\s*:\s*(.+?)\s*$", text.split("\n## ")[0], re.M)
    return m.group(1) if m else None


def _outcome_from_operative(operative: str) -> str:
    """Last resort for an empty outcome: the operative part's first ruling, verbatim, without markup."""
    body = re.sub(r"^#+[^\n]*\n|\*+", "", operative.strip()).strip()
    body = re.sub(r"^(?:حكمت المحكمة|The court rules)\s*:?\s*", "", body).strip()
    first = re.split(r"\n\s*\n|\n\s*2\.", body)[0]
    return re.sub(r"^\s*1\.\s*", "", re.sub(r"\s+", " ", first)).strip()[:400]


def _operative_amounts(operative: str, units: dict[str, str]) -> list[str]:
    """Amounts written with a currency unit in the operative part, in order, with the source's unit."""
    src = operative.translate(_DIGITS)
    found = [m.group(1) for m in re.finditer(r"(\d[\d,.]*\d)\s*" + _UNIT, src)]
    found += [m.group(1) for m in re.finditer(r"EGP\s*(\d[\d,.]*\d)", src)]
    return list(dict.fromkeys(_with_unit(n, units) for n in found))


def _check_split(split: list[dict] | None, operative: str, units: dict[str, str]) -> list[dict] | None:
    """Keep split rows whose amount is in the operative part; reattach units. Rows the operative part does
    not support are dropped rather than shown with a possibly wrong party."""
    if not split:
        return None
    awarded = set(_numbers(operative))
    rows = []
    for s in split:
        if not (set(_numbers(s.get("amount", ""))) & awarded):
            continue
        s["amount"] = _with_unit(s["amount"], units)
        rows.append(s)
    # Payers first, then the share a party bears itself
    rows.sort(key=lambda s: s.get("role") != "pays")
    return rows or None


def _compound_flags(compound: list[dict], en: bool) -> list[dict]:
    """Compound risks (computed in code) as risk flags after the per-article ones."""
    flags = []
    for c in compound:
        arts = sorted({int(a) for a in c.get("articles", [])})
        if not arts:
            continue
        label = " + ".join(f"{'Art.' if en else 'م.'}{a}" for a in arts)
        flags.append({"article": arts[0], "articles": arts, "compound": True, "severity": c["severity"],
                      "title": f"{'Compound risk' if en else 'خطر مركب'} ({label})", "risk": c["risk"], "changes": []})
    return flags


def _unsupported_amounts(amounts: list[str], source: str, en: bool) -> list[dict]:
    """Self-check: every number in a summary amount must occur in the source text."""
    known = set(_numbers(source))
    flags = []
    for a in amounts:
        missing = [n for n in _numbers(a) if n not in known]
        if missing:
            flags.append({"article": 0, "title": "Amount check" if en else "التحقق من المبالغ", "severity": "medium",
                          "risk": (f"Amount not found in the source text: {a}" if en
                                   else f"مبلغ في الملخص غير موجود في نص الوثيقة: {a}"),
                          "changes": [{"aspect": "amount" if en else "المبلغ", "template": "", "contract": a}]})
    return flags


FALLBACK_ALIAS = os.getenv("D5_FALLBACK_ALIAS", "quality")


def _usable_verdict(d: dict | None) -> bool:
    """A comparison verdict the model wrote itself: deviates present (not filled by repair_json), and a
    valid severity when it deviates. Strips the repair marker."""
    if d is None:
        return False
    filled = d.pop("_filled", [])
    return "deviates" not in filled and (not d["deviates"] or d.get("severity") in ("low", "medium", "high"))


_SEVERITY_WORDS = {"", "high", "medium", "low", "none", "مرتفع", "مرتفعة", "عالي", "عالية", "متوسط", "متوسطة",
                   "منخفض", "منخفضة"}


def _risk_text(d: dict, en: bool) -> str:
    """The risk sentence, or the changed aspects when the model put only the severity word there
    (Gemma 4 26B on vLLM answered "high" for most Arabic articles)."""
    risk = (d.get("risk") or "").strip()
    if re.sub(r"[\s.*:،]", "", risk).lower() not in _SEVERITY_WORDS:
        return risk
    aspects = [c["aspect"] for c in d.get("changes") or [] if isinstance(c, dict) and c.get("aspect")]
    if not aspects:
        return risk
    return ("Deviates from the approved template in: " + "; ".join(aspects) if en
            else "انحراف عن النموذج المعتمد في: " + "؛ ".join(aspects))


async def template_diff(chunks: list[dict], trace: Trace, en: bool = False) -> tuple[list, list]:
    template = split_clauses((SEED / "template.md").read_text(encoding="utf-8"))
    by_no = {c["no"]: c for c in chunks}

    async def compare(t):
        c = by_no.get(t["no"])
        if c is None:
            return {"article": t["no"], "title": t["title"], "status": "missing", "severity": "high",
                    "changes": [{"aspect": "Whole article" if en else "المادة كاملة", "template": t["title"],
                                 "contract": "Missing" if en else "غير موجودة"}],
                    "risk": "Removing a template article removes a contractual protection" if en
                            else "حذف مادة من النموذج المعتمد يزيل حماية تعاقدية", "template": t["text"], "contract": None}
        if re.sub(r"\s+", "", t["text"]) == re.sub(r"\s+", "", re.sub(r"\[[^\]]+\]", "", c["text"])) or \
           _same_after_fill(t["text"], c["text"]):
            return {"article": t["no"], "title": t["title"], "status": "same", "severity": "none", "changes": [], "risk": "",
                    "template": t["text"], "contract": c["text"]}
        # English contracts get the instruction in English too: an Arabic prompt over an English article
        # is where Gemma most often produced malformed JSON (E01 in the stability runs)
        messages = [{"role": "user", "content": (
            "Compare the article in the contract with the same article in the approved template (the template is in Arabic). "
            "Ignore differences in the client's name, amounts and number of instalments; focus on the terms: periods, rates, "
            "rights, notice, governing law and jurisdiction, liability, data. If it deviates, list each change: the aspect, "
            "the template's value and the contract's value, then the severity for the bank and for client protection. "
            "In risk, write one sentence on what the deviation means for the bank or the client "
            "(the consequence, not the severity word). "
            f"{SEVERITY_RUBRIC_EN} Answer in English.\n\n"
            f"Approved template:\n{t['text']}\n\nContract:\n{c['text']}") if en else (
            "قارن المادة في العقد بنفس المادة في النموذج المعتمد. تجاهل الفروق في الأسماء والمبالغ وعدد الأقساط الخاصة بالعميل، "
            "وركّز على الأحكام: المدد، النسب، الحقوق، الإنذار، القانون والاختصاص، المسؤولية، البيانات. "
            "إن وُجد انحراف فاذكر كل تغيير: الجانب، والقيمة في النموذج، والقيمة في العقد، ثم مستوى الخطورة على البنك وحماية العميل. "
            "واكتب في risk جملة واحدة تشرح أثر الانحراف على البنك أو على العميل (الأثر نفسه، لا كلمة مستوى الخطورة). "
            f"{SEVERITY_RUBRIC} اكتب الإجابة بالعربية.\n\n"
            f"النموذج المعتمد:\n{t['text']}\n\nالعقد:\n{c['text']}")}]
        # Malformed output: chat_json_d5 retries and repairs a truncated reply. A repair is only trusted if the
        # model itself wrote the verdict (deviates, and severity when it deviates); otherwise the article is
        # reported as unchecked instead of failing the whole document or guessing.
        d, r = await chat_json_d5(messages, DIFF_SCHEMA, max_tokens=350 if en else 1000, temperature=0)
        # English: Gemma pads with whitespace up to the cap, so keep it near the 60-250 token verdict.
        # Arabic takes far more tokens per verdict (C03 art 12 was cut off at 350) and does not pad.
        if not _usable_verdict(d):
            # One more try on a different model for this article only: the workhorse's unusable replies
            # (about 1 run in 3 on OpenRouter) are rarely repeated by the 31B on the same article.
            # On the GB10 without the quality profile, the gateway serves this from the workhorse.
            d, r = await chat_json_d5(messages, DIFF_SCHEMA, alias=FALLBACK_ALIAS,
                                      max_tokens=350 if en else 1000, temperature=0)
        if not _usable_verdict(d):
            return {"article": t["no"], "title": t["title"], "status": "unchecked", "severity": "unchecked",
                    "changes": [], "risk": "comparison failed: malformed model output",
                    "template": t["text"], "contract": c["text"]}
        severity = d["severity"] if d["deviates"] else "none"
        if t["no"] in MEDIUM_ARTICLES and severity == "high":
            severity = "medium"
        return {"article": t["no"], "title": t["title"], "status": "deviates" if d["deviates"] else "same",
                "severity": severity, "changes": d["changes"], "risk": _risk_text(d, en) if d["deviates"] else d["risk"],
                "template": t["text"], "contract": c["text"], "_ms": r.latency_ms if r else 0}

    rows = await asyncio.gather(*(compare(t) for t in template))
    compared = [r for r in rows if "_ms" in r]
    unchecked = [r["article"] for r in rows if r["status"] == "unchecked"]
    trace.add("llm", f"Compare {len(template)} articles with the approved template ({len(compared)} needed the LLM)",
              {"deviations": sum(r["status"] in ("deviates", "missing") for r in rows), "unchecked": unchecked},
              max((r.pop("_ms") for r in compared), default=0))
    order = {"high": 0, "medium": 1, "low": 2, "none": 3}
    flags = sorted([{"article": r["article"], "title": r["title"], "severity": r["severity"], "risk": r["risk"], "changes": r["changes"]}
                    for r in rows if r["status"] in ("deviates", "missing")], key=lambda f: order[f["severity"]])
    return rows, flags


def _same_after_fill(template: str, contract: str) -> bool:
    """Template placeholders ([المبلغ] etc.) are filled in contracts; treat a filled copy as identical."""
    pattern = re.escape(re.sub(r"\s+", " ", template.strip()))
    pattern = re.sub(r"\\\[[^\]]+\\\]", ".+?", pattern)
    return re.fullmatch(pattern, re.sub(r"\s+", " ", contract.strip())) is not None


class AnalyzeIn(BaseModel):
    file: str


@app.post("/analyze")
async def analyze(body: AnalyzeIn):
    name = Path(body.file).name
    path = SEED / name
    if not path.exists():
        raise HTTPException(404, "unknown document")
    if name not in CACHE:
        kind = "template" if name == "template.md" else "ruling" if name.startswith("R") else "contract"
        CACHE[name] = await analyze_text(name, path.read_text(encoding="utf-8"), kind)
    return CACHE[name]


@app.post("/analyze/refresh")
async def analyze_refresh(body: AnalyzeIn):
    CACHE.pop(Path(body.file).name, None)
    return await analyze(body)


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    """Uploaded contract or ruling: Docling for source formats; Arabic PDFs are rendered and read by the vision model."""
    data = await file.read()
    trace_note = []
    if (file.filename or "").lower().endswith((".md", ".txt")):
        conv = {"markdown": data.decode("utf-8-sig")}       # already text: no Docling round trip
    else:
        try:
            conv = await platform.convert_document(file.filename or "upload.pdf", data)
        except httpx.HTTPError as exc:
            raise HTTPException(503, "The document converter is not reachable, so PDF and Word files cannot be read. "
                                     "Upload a .md or .txt file instead.") from exc
    text = conv["markdown"]
    if conv.get("rtl_pdf"):
        pages = await platform.render_pdf(data)
        async def read(png):
            r = await llm.chat([{"role": "user", "content": [llm.image_part(png), {"type": "text", "text":
                     "انسخ نص هذه الصفحة إلى Markdown كما هو تماماً، مع العناوين والأرقام. أخرج النص فقط."}]}], "vision", max_tokens=1800, temperature=0)
            return r.text
        text = "\n\n".join(await asyncio.gather(*(read(p) for p in pages[:30])))
        trace_note.append(f"Arabic PDF: {len(pages)} page(s) transcribed by the vision model (Docling's text layer is unreliable for RTL)")
    kind = "contract" if re.search(r"المادة|\bArticle\s+\d", text) else "ruling"
    result = await analyze_text(file.filename or "upload", text, "upload" if kind == "contract" else "ruling")
    for n in trace_note:
        result["trace"].insert(0, {"kind": "ingest", "label": n, "detail": None, "ms": None, "at_ms": 0})
    return result


@app.get("/golden")
def golden():
    """Planted deviations (from the specs) for checking the comparison on stage or in tests."""
    p = SEED.parent / "golden" / "d5.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
