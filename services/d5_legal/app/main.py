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
from pathlib import Path

from fastapi import File, HTTPException, UploadFile
from pydantic import BaseModel

from nbe_core import create_app, llm, platform, retrieval
from nbe_core.trace import Trace

SEED = Path("/data/seed/d5")
REDUCE_ALIAS = os.getenv("D5_REDUCE_ALIAS", "workhorse")
COLLECTION = "d5_legal"
app = create_app("d5", "Legal Documents Summarization", phase="wave1")
CACHE: dict[str, dict] = {}

CLAUSE_TYPES = {
    "governing_law": "القانون الواجب التطبيق والاختصاص القضائي أو التحكيم",
    "late_payment": "التأخر في السداد والغرامات والتعجيل",
    "prepayment": "السداد المعجل",
    "rate": "العائد أو الفائدة وتعديلها",
    "termination": "إنهاء العقد",
    "liability": "حدود المسؤولية والتعويض",
    "insurance": "التأمين",
    "data": "سرية البيانات ومشاركتها",
    "security": "الضمانات",
}


def split_clauses(md: str) -> list[dict]:
    """Contracts: one chunk per article (المادة N). Rulings: one chunk per ## section."""
    parts = re.split(r"\n(?=(?:#+\s*)?\**المادة\s+\d+)", md)
    if len(parts) > 2:
        out = []
        for p in parts:
            m = re.match(r"(?:#+\s*)?\**المادة\s+(\d+)\s*[-–:]?\s*([^\n*]*)", p.strip())
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


SUMMARY_SCHEMA = {"type": "object", "properties": {
    "document_type": {"type": "string"}, "parties": {"type": "array", "items": {"type": "string"}},
    "key_points": {"type": "array", "items": {"type": "string"}, "maxItems": 7},
    "outcome_or_obligations": {"type": "string"}, "amounts": {"type": "array", "items": {"type": "string"}}},
    "required": ["document_type", "parties", "key_points", "outcome_or_obligations", "amounts"]}

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
    chunks = split_clauses(text)
    trace.add("chunk", f"Split into {len(chunks)} parts", [c["title"] for c in chunks])

    # Map: summarise each part in parallel (fast workhorse)
    async def map_one(c):
        r = await llm.chat([{"role": "user", "content": f"لخّص هذا الجزء من وثيقة قانونية في جملتين بالعربية، مع ذكر أي أرقام أو مدد كما هي:\n\n{c['text']}"}],
                           max_tokens=220, temperature=0)
        return c, r
    mapped = await asyncio.gather(*(map_one(c) for c in chunks))
    trace.add("llm", f"Map: summarise {len(chunks)} parts in parallel (workhorse)",
              {"parts": len(chunks), "tokens": sum(r.completion_tokens for _, r in mapped)},
              max(r.latency_ms for _, r in mapped))
    partials = "\n".join(f"- ({c['title']}) {r.text.strip()}" for c, r in mapped)

    # Reduce: one structured summary from the partial summaries
    summary, res = await llm.chat_json([{"role": "user", "content":
        "من ملخصات الأجزاء التالية لوثيقة قانونية، اكتب ملخصاً منظماً بالعربية لموظف الشؤون القانونية: نوع الوثيقة، الأطراف، "
        "أهم النقاط (5 إلى 7)، المنطوق أو الالتزامات الرئيسية، والمبالغ المذكورة كما هي.\n\n" + partials}],
        SUMMARY_SCHEMA, alias=REDUCE_ALIAS, max_tokens=1200)
    trace.llm(f"Reduce: structured summary ({REDUCE_ALIAS})", res)

    result = {"name": name, "kind": kind, "summary": summary, "clauses": [], "diff": [], "risk_flags": []}
    if kind in ("contract", "template", "upload"):
        clauses, res = await llm.chat_json([{"role": "user", "content":
            "استخرج من العقد التالي البنود من الأنواع المحددة فقط إن وُجدت. لكل بند: النوع، رقم المادة، ملخص بجملة، واقتباس حرفي قصير من النص يثبت البند.\n"
            "الأنواع: " + "؛ ".join(f"{k} = {v}" for k, v in CLAUSE_TYPES.items()) + f"\n\nالعقد:\n{text}"}],
            CLAUSE_SCHEMA, max_tokens=2500)
        trace.llm("Schema-guided clause extraction (workhorse)", res)
        # Keep only quotes that really occur in the document: an unverifiable quote is dropped, not shown
        flat = re.sub(r"\s+", " ", text)
        for c in clauses["clauses"]:
            c["quote_verified"] = re.sub(r"\s+", " ", c["quote"]).strip(" .\"«»") in flat
        result["clauses"] = clauses["clauses"]
        if kind != "template":
            result["diff"], result["risk_flags"] = await template_diff(chunks, trace)
    result["trace"] = trace.to_list()
    result["total_ms"] = trace.total_ms()
    return result


async def template_diff(chunks: list[dict], trace: Trace) -> tuple[list, list]:
    template = split_clauses((SEED / "template.md").read_text(encoding="utf-8"))
    by_no = {c["no"]: c for c in chunks}

    async def compare(t):
        c = by_no.get(t["no"])
        if c is None:
            return {"article": t["no"], "title": t["title"], "status": "missing", "severity": "high",
                    "changes": [{"aspect": "المادة كاملة", "template": t["title"], "contract": "غير موجودة"}], "risk": "حذف مادة من النموذج المعتمد يزيل حماية تعاقدية", "template": t["text"], "contract": None}
        if re.sub(r"\s+", "", t["text"]) == re.sub(r"\s+", "", re.sub(r"\[[^\]]+\]", "", c["text"])) or \
           _same_after_fill(t["text"], c["text"]):
            return {"article": t["no"], "title": t["title"], "status": "same", "severity": "none", "changes": [], "risk": "",
                    "template": t["text"], "contract": c["text"]}
        d, r = await llm.chat_json([{"role": "user", "content":
            "قارن المادة في العقد بنفس المادة في النموذج المعتمد. تجاهل الفروق في الأسماء والمبالغ وعدد الأقساط الخاصة بالعميل، "
            "وركّز على الأحكام: المدد، النسب، الحقوق، الإنذار، القانون والاختصاص، المسؤولية، البيانات. "
            "إن وُجد انحراف فاذكر كل تغيير: الجانب، والقيمة في النموذج، والقيمة في العقد، ثم مستوى الخطورة على البنك وحماية العميل.\n\n"
            f"النموذج المعتمد:\n{t['text']}\n\nالعقد:\n{c['text']}"}], DIFF_SCHEMA, max_tokens=700)
        return {"article": t["no"], "title": t["title"], "status": "deviates" if d["deviates"] else "same",
                "severity": d["severity"] if d["deviates"] else "none", "changes": d["changes"], "risk": d["risk"],
                "template": t["text"], "contract": c["text"], "_ms": r.latency_ms}

    rows = await asyncio.gather(*(compare(t) for t in template))
    compared = [r for r in rows if "_ms" in r]
    trace.add("llm", f"Compare {len(template)} articles with the approved template ({len(compared)} needed the LLM)",
              {"deviations": sum(r["status"] != "same" for r in rows)}, max((r.pop("_ms") for r in compared), default=0))
    order = {"high": 0, "medium": 1, "low": 2, "none": 3}
    flags = sorted([{"article": r["article"], "title": r["title"], "severity": r["severity"], "risk": r["risk"], "changes": r["changes"]}
                    for r in rows if r["status"] != "same"], key=lambda f: order[f["severity"]])
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
    conv = await platform.convert_document(file.filename or "upload.pdf", data)
    text = conv["markdown"]
    if conv.get("rtl_pdf"):
        pages = await platform.render_pdf(data)
        async def read(png):
            r = await llm.chat([{"role": "user", "content": [llm.image_part(png), {"type": "text", "text":
                     "انسخ نص هذه الصفحة إلى Markdown كما هو تماماً، مع العناوين والأرقام. أخرج النص فقط."}]}], "vision", max_tokens=1800, temperature=0)
            return r.text
        text = "\n\n".join(await asyncio.gather(*(read(p) for p in pages[:30])))
        trace_note.append(f"Arabic PDF: {len(pages)} page(s) transcribed by the vision model (Docling's text layer is unreliable for RTL)")
    kind = "contract" if "المادة" in text else "ruling"
    result = await analyze_text(file.filename or "upload", text, "upload" if kind == "contract" else "ruling")
    for n in trace_note:
        result["trace"].insert(0, {"kind": "ingest", "label": n, "detail": None, "ms": None, "at_ms": 0})
    return result


@app.get("/golden")
def golden():
    """Planted deviations (from the specs) for checking the comparison on stage or in tests."""
    p = Path("/data/seed/golden/d5.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
