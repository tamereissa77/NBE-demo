"""D2 · Chat with Document (PLAN.md §4 D2).

A branch employee asks about a working procedure, in Arabic, dialect or English. The answer cites the
current version, and a "what changed" panel compares it with the previous version.

Retrieval is shared with D5 through nbe_core.retrieval (bge-m3 + Qdrant + bge-reranker-v2-m3).
"""
import difflib
import json
import re
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel

from nbe_core import create_app, llm, retrieval
from nbe_core.text import detect_lang
from nbe_core.trace import Trace

SEED = Path("/data/seed/d2")
COLLECTION = "d2_procedures"
app = create_app("d2", "Chat with Document", phase="wave1")
DOCS: dict[str, dict] = {}          # file -> manifest entry + text + sections
DELTA_CACHE: dict[str, dict] = {}   # procedure -> delta summary


def sections(md: str) -> list[dict]:
    """Split Markdown into (heading, text) sections, keeping the document title as context."""
    out, heading, buf = [], "مقدمة", []
    for line in md.splitlines():
        if line.startswith("## "):
            if "".join(buf).strip():
                out.append({"heading": heading, "text": "\n".join(buf).strip()})
            heading, buf = line[3:].strip(), []
        elif not line.startswith("# "):
            buf.append(line)
    if "".join(buf).strip():
        out.append({"heading": heading, "text": "\n".join(buf).strip()})
    return out


def load_docs() -> None:
    if DOCS or not (SEED / "manifest.json").exists():
        return
    for m in json.loads((SEED / "manifest.json").read_text(encoding="utf-8")):
        text = (SEED / m["file"]).read_text(encoding="utf-8")
        DOCS[m["file"]] = {**m, "text": text, "sections": sections(text)}


@app.on_event("startup")
def _startup() -> None:
    load_docs()


@app.post("/admin/ingest")
async def ingest():
    load_docs()
    if not DOCS:
        raise HTTPException(409, "no seed documents; run the authoring step first")
    await retrieval.ensure_collection(COLLECTION, recreate=True)
    texts, payloads = [], []
    for f, d in DOCS.items():
        for i, s in enumerate(d["sections"]):
            texts.append(f"{d['title']} - الإصدار {d['version']}\n{s['heading']}\n{s['text']}")
            payloads.append({"file": f, "procedure": d["procedure"], "version": d["version"], "lang": d["lang"],
                             "effective": d["effective"], "title": d["title"], "section": s["heading"], "section_no": i})
    n = await retrieval.upsert(COLLECTION, texts, payloads)
    DELTA_CACHE.clear()
    return {"ingested_sections": n, "documents": len(DOCS)}


@app.get("/documents")
def documents():
    load_docs()
    procs: dict[str, dict] = {}
    for d in DOCS.values():
        p = procs.setdefault(d["procedure"], {"procedure": d["procedure"], "versions": []})
        if d["lang"] == "ar":
            p["title"] = d["title"]
        p["versions"].append({"file": d["file"], "version": d["version"], "lang": d["lang"], "effective": d["effective"]})
    return sorted(procs.values(), key=lambda p: p["procedure"])


@app.get("/doc/{file}")
def doc(file: str):
    load_docs()
    if file not in DOCS:
        raise HTTPException(404, "unknown document")
    d = DOCS[file]
    return {k: d[k] for k in ("file", "title", "version", "lang", "effective", "text")}


class Ask(BaseModel):
    question: str
    history: list[dict] = []


COMPARE = re.compile(r"(تغي[ّ]?ر|اتغير|الفرق بين|الفروق|ما الجديد|إيه اللي اتغير|what changed|what's new|difference between|compare)", re.I)

ANSWER_SYSTEM = {
    "ar": ("أنت مساعد موظفي فروع البنك الأهلي المصري. أجب فقط من المصادر المرفقة. اذكر المصدر بعد كل معلومة بالشكل [S1] أو [S2]. "
           "إذا لم تجد الإجابة في المصادر فقل بوضوح: \"لم أجد هذه المعلومة في الإجراءات المتاحة\" ولا تخمّن. "
           "إذا ظهرت عدة إصدارات لنفس الإجراء فاعتمد الإصدار الأحدث وأشر إلى ذلك. أجب بالعربية الفصحى بإيجاز، "
           "حتى لو كان السؤال بالعامية المصرية. لا تبدأ بمقدمة."),
    "en": ("You assist National Bank of Egypt branch staff. Answer only from the attached sources and cite each fact as [S1], [S2]. "
           "If the answer is not in the sources, say \"I could not find this in the available procedures\" and do not guess. "
           "If several versions of a procedure appear, use the latest and say so. Answer in English, concisely, with no preamble."),
}


async def version_delta(procedure: str, lang: str, trace: Trace) -> dict | None:
    """Section-level diff between v1 and v2 (Arabic originals) plus an LLM summary of the changes."""
    v1, v2 = DOCS.get(f"{procedure}_v1_ar.md"), DOCS.get(f"{procedure}_v2_ar.md")
    if not (v1 and v2):
        return None
    key = f"{procedure}:{lang}"
    if key not in DELTA_CACHE:
        diff = []
        old = {s["heading"]: s["text"] for s in v1["sections"]}
        for s in v2["sections"]:
            before = old.get(s["heading"], "")
            if before.strip() != s["text"].strip():
                diff.append({"section": s["heading"], "before": before, "after": s["text"],
                             "similarity": round(difflib.SequenceMatcher(None, before, s["text"]).ratio(), 2)})
        prompt = ("قارن بين الإصدارين التاليين من نفس الإجراء واذكر التغييرات الجوهرية فقط في نقاط قصيرة (القيمة القديمة ← الجديدة). "
                  "لا تذكر تغييرات الصياغة. استخدم السهم → فقط، بدون LaTeX أو رموز رياضية. " + ("أجب بالإنجليزية." if lang == "en" else "أجب بالعربية.") +
                  f"\n\n=== الإصدار 1 ({v1['effective']}) ===\n{v1['text']}\n\n=== الإصدار 2 ({v2['effective']}) ===\n{v2['text']}")
        res = await llm.chat([{"role": "user", "content": prompt}], max_tokens=500, temperature=0)
        trace.llm("Summarise what changed between versions", res)
        DELTA_CACHE[key] = {"procedure": procedure, "title": v2["title"], "from": {"version": 1, "effective": v1["effective"]},
                            "to": {"version": 2, "effective": v2["effective"]}, "summary": res.text.strip(), "sections": diff}
    else:
        trace.add("cache", "Version comparison (cached)")
    return DELTA_CACHE[key]


@app.post("/ask")
async def ask(body: Ask):
    load_docs()
    trace = Trace()
    lang = detect_lang(body.question)
    with trace.step("retrieval", "Search procedures (bge-m3 → Qdrant → bge-reranker)") as s:
        hits = await retrieval.search(COLLECTION, body.question, k=6, candidates=24)
        s["detail"] = [{"title": h["title"], "version": h["version"], "lang": h["lang"], "section": h["section"],
                        "rerank": h["rerank_score"]} for h in hits]
    if not hits or hits[0]["rerank_score"] < 0.02:
        msg = "لم أجد هذه المعلومة في الإجراءات المتاحة." if lang == "ar" else "I could not find this in the available procedures."
        return {"answer": msg, "citations": [], "delta": None, "trace": trace.to_list(), "found": False}

    # "What changed?" questions are answered from the version comparison, citing both versions
    if COMPARE.search(body.question):
        proc = hits[0]["file"].split("_")[0]
        delta = await version_delta(proc, lang, trace)
        if delta:
            files = [f"{proc}_v1_ar.md", f"{proc}_v2_ar.md"]
            citations = [{"label": f"S{i + 1}", "file": f, "title": DOCS[f]["title"], "version": DOCS[f]["version"], "lang": "ar",
                          "effective": DOCS[f]["effective"], "section": "", "text": DOCS[f]["text"][:400], "rerank": None, "cited": True}
                         for i, f in enumerate(files)]
            head = (f"التغييرات في «{delta['title']}» بين الإصدار 1 [S1] والإصدار 2 [S2]:\n\n" if lang == "ar"
                    else f"Changes in “{delta['title']}” between version 1 [S1] and version 2 [S2]:\n\n")
            return {"answer": head + delta["summary"], "citations": citations, "delta": delta, "found": True, "lang": lang,
                    "trace": trace.to_list(), "total_ms": trace.total_ms()}

    # Prefer the current version: if a procedure appears in both versions, put the newest first
    latest = {}
    for d in DOCS.values():
        latest[d["procedure"]] = max(latest.get(d["procedure"], 0), d["version"])
    hits.sort(key=lambda h: (h["version"] != latest[h["procedure"]], -h["rerank_score"]))
    sources = hits[:5]
    context = "\n\n".join(f"[S{i + 1}] {h['title']} · الإصدار {h['version']} (ساري من {h['effective']}) · {h['section']}\n{h['text']}"
                          for i, h in enumerate(sources))
    messages = [{"role": "system", "content": ANSWER_SYSTEM[lang]}, *body.history[-4:],
                {"role": "user", "content": f"المصادر:\n{context}\n\n---\nالسؤال: {body.question}"}]
    res = await llm.chat(messages, max_tokens=700, temperature=0)
    trace.llm("Write the cited answer (workhorse)", res)

    cited = sorted({int(n) for n in re.findall(r"\[S(\d+)\]", res.text) if 0 < int(n) <= len(sources)})
    citations = [{"label": f"S{i + 1}", "file": h["file"], "title": h["title"], "version": h["version"], "lang": h["lang"],
                  "effective": h["effective"], "section": h["section"], "text": h["text"].split("\n", 2)[-1],
                  "rerank": h["rerank_score"], "cited": (i + 1) in cited} for i, h in enumerate(sources)]
    primary = next((c for c in citations if c["cited"]), citations[0])
    delta = await version_delta(primary["file"].split("_")[0], lang, trace)
    not_found = any(p in res.text for p in ("لم أجد", "could not find"))
    return {"answer": res.text.strip(), "citations": citations, "delta": None if not_found else delta,
            "found": not not_found, "lang": lang, "trace": trace.to_list(), "total_ms": trace.total_ms()}


@app.get("/suggested")
def suggested():
    return [
        {"lang": "ar", "q": "ما رسوم استبدال بطاقة الائتمان المفقودة الآن؟ وهل تغيّرت؟"},
        {"lang": "egy", "q": "لو العميل عايز يرفع حد التحويل لـ 150 ألف، يعمل إيه؟"},
        {"lang": "ar", "q": "ما المستندات المطلوبة للتمويل الشخصي للموظفين؟"},
        {"lang": "en", "q": "What is the commission on outgoing international transfers?"},
        {"lang": "ar", "q": "هل يمكن إرسال البطاقة البديلة إلى منزل العميل بالبريد؟"},
    ]
