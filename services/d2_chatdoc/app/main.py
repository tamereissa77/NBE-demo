"""D2 · Chat with Document (PLAN.md §4 D2).

A branch employee asks about a working procedure, in Arabic, local dialect or English. The answer cites the
current version, and a "what changed" panel compares it with the previous version.

Retrieval is shared with D5 through nbe_core.retrieval (bge-m3 + Qdrant + bge-reranker-v2-m3).

A second, optional corpus holds documents that exist only as page scans (circulars, the RTGS guide):
see app/scans.py. It lives in its own collection, its citations carry the crop images of the scan,
and each document lists the roles allowed to read it. Without /data/seed/d2/circulars the service
behaves exactly as the procedures-only D2.

New scanned documents can be added without re-ingesting (back office, manager only): app/intake.py sends
an uploaded PDF to the extraction service (services/d2_extraction) and adds only its passages. That path
exists only with docker-compose.d2-extract.yml.

With that corpus come the guardrails nbe-working had, here on the local guardrails service (policy
config/guardrails/d2): an input check before retrieval, and on every generated answer a rule that masks
personal identifiers followed by an output check.
"""
import difflib
import json
import re
from pathlib import Path

import httpx
from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import intake, scans
from nbe_core import create_app, llm, platform, retrieval, settings
from nbe_core import locale as L
from nbe_core.text import detect_lang
from nbe_core.trace import Trace

SEED = Path("/data/seed/d2")
COLLECTION = "d2_procedures"
SCAN_COLLECTION = "d2_circulars"
DEFAULT_ROLE = "manager"            # sees every document, so callers that send no role get all sources
FOUND_MIN = 0.02                    # reranker score under which nothing relevant was retrieved
# A passage the role may not read counts as "the answer exists but is restricted" from this score up.
# Provisional until calibrated on a scanned-corpus golden set (docs/d2-migration-log.md).
RESTRICTED_MIN = 0.3
GUARD_CONFIG = "d2"                 # policy folder under config/guardrails, loaded by the nbe-guardrails service
_D = "[0-9٠-٩]"
# Personal identifiers that must not appear in an answer whatever the model does: a card number (16 digits),
# and the country's national ID and mobile numbers (nbe_core.locale.PII_RE), in either digit script
PII = re.compile(rf"(?<!{_D})(?:{_D}{{16}}|" + L.PII_RE.replace("{D}", _D) + rf")(?!{_D})")
app = create_app("d2", "Chat with Document", phase="wave1")
DOCS: dict[str, dict] = {}          # file -> manifest entry + text + sections
DELTA_CACHE: dict[str, dict] = {}   # procedure -> delta summary
SCANS: dict = {}                    # scanned corpus {docs, passages, crops}; empty when not installed


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


def load_scans() -> None:
    """The seed corpus plus any documents added through app/intake.py (none unless that volume is mounted)."""
    fresh = scans.load_all([SEED / "circulars", intake.CORPUS]) or {}
    SCANS.clear()
    SCANS.update(fresh)


def load_docs() -> None:
    if not SCANS:
        load_scans()
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
    out = {"ingested_sections": n, "documents": len(DOCS)}
    if SCANS:
        await retrieval.ensure_collection(SCAN_COLLECTION, recreate=True)
        out["scanned_passages"] = await retrieval.upsert(SCAN_COLLECTION, *scan_points(SCANS["passages"]))
        out["scanned_documents"] = len(SCANS["docs"])
    return out


def scan_points(passages: list[dict]) -> tuple[list[str], list[dict]]:
    """Texts to embed and their payloads, for the scanned collection."""
    docs = SCANS["docs"]
    return [p["embed"] for p in passages], [
        {"kind": "scan", "doc_id": p["doc_id"], "title": docs[p["doc_id"]]["title_ar"], "title_en": docs[p["doc_id"]]["title_en"],
         "lang": docs[p["doc_id"]]["lang"], "roles": docs[p["doc_id"]]["roles"], "page": p["page"], "section": p["heading"],
         "block_type": p["block_type"], "display": p["display"], "blocks": p["blocks"], "passage": p["id"]}
        for p in passages]


async def index_doc(doc_id: str) -> int:
    """Make the collection match the corpus for ONE scanned document: drop its passages, add the current
    ones (none if the document is gone). Every other document, and the procedures collection, is untouched."""
    load_scans()
    await retrieval.ensure_collection(SCAN_COLLECTION)
    async with httpx.AsyncClient(timeout=120, base_url=settings.qdrant_url) as client:
        r = await client.post(f"/collections/{SCAN_COLLECTION}/points/delete?wait=true",
                              json={"filter": {"must": [{"key": "doc_id", "match": {"value": doc_id}}]}})
        r.raise_for_status()
    mine = [p for p in SCANS.get("passages", []) if p["doc_id"] == doc_id]
    return await retrieval.upsert(SCAN_COLLECTION, *scan_points(mine)) if mine else 0


app.include_router(intake.build_router(index_doc))


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


@app.get("/corpus")
def corpus():
    """The scanned corpus and the roles that gate it; empty lists when it is not installed."""
    load_docs()
    return {"roles": scans.ROLES if SCANS else [], "default_role": DEFAULT_ROLE,
            "documents": [{k: d[k] for k in ("doc_id", "title_ar", "title_en", "type", "pages", "passages", "roles")}
                          for d in SCANS.get("docs", {}).values()]}


@app.get("/crop/{doc_id}/{block_id}")
def crop(doc_id: str, block_id: str, role: str = DEFAULT_ROLE):
    """Crop image of one OCR block, as shown beside a citation. Ids are looked up, never used as paths."""
    load_docs()
    doc, (owner, path) = SCANS.get("docs", {}).get(doc_id), SCANS.get("crops", {}).get(block_id, (None, None))
    if not doc or owner != doc_id or not path.exists():
        raise HTTPException(404, "unknown crop")
    if role not in doc["roles"]:
        raise HTTPException(403, "this role may not read the document")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


class Ask(BaseModel):
    question: str
    history: list[dict] = []
    role: str = DEFAULT_ROLE


COMPARE = re.compile(r"(تغي[ّ]?ر|اتغير|الفرق بين|الفروق|ما الجديد|إيه اللي اتغير|وش اللي تغير|ايش اللي تغير|وش الفرق|what changed|what's new|difference between|compare)", re.I)

ANSWER_SYSTEM = {
    "ar": (f"أنت مساعد موظفي فروع {settings.bank_ar}. أجب فقط من المصادر المرفقة. اذكر المصدر بعد كل معلومة بالشكل [S1] أو [S2]. "
           "إذا لم تجد الإجابة في المصادر فقل بوضوح: \"لم أجد هذه المعلومة في الإجراءات المتاحة\" ولا تخمّن. "
           "إذا ظهرت عدة إصدارات لنفس الإجراء فاعتمد الإصدار الأحدث وأشر إلى ذلك. أجب بالعربية الفصحى بإيجاز، "
           f"حتى لو كان السؤال ب{L.DIALECT_AR}. لا تبدأ بمقدمة."),
    "en": (f"You assist {settings.bank_en} branch staff. Answer only from the attached sources and cite each fact as [S1], [S2]. "
           "If the answer is not in the sources, say \"I could not find this in the available procedures\" and do not guess. "
           "If several versions of a procedure appear, use the latest and say so. Answer in English, concisely, with no preamble."),
}


# Added to the system prompt only when a scanned source is in the context, so procedure answers are unchanged
SCAN_NOTE = {
    "ar": " بعض المصادر مستخرجة من مستندات ممسوحة ضوئياً وقد تحتوي على جداول أو قوائم: اقرأها بعناية واستخرج المعلومة منها مباشرة.",
    "en": " Some sources are extracted from scanned documents and may contain tables or lists: read them carefully and take the facts directly from them.",
}
# Wording kept from nbe-working's teller refusal
RESTRICTED = {
    "ar": "بعتذر لحضرتك بس صلاحيات حسابك مش بتسمح بالاطلاع على المستندات الخاصة بهذا الموضوع.",
    "en": "Sorry, your role does not have access to the documents that cover this topic.",
}


REDACTED = {"ar": "[محجوب]", "en": "[redacted]"}
BLOCKED = {
    "input": {"ar": "لا يمكنني المساعدة في هذا الطلب. يمكنني الإجابة عن الأسئلة المتعلقة بإجراءات العمل والتعميمات المصرفية.",
              "en": "I can't help with that request. I can answer questions about working procedures and banking circulars."},
    "output": {"ar": "تم حجب الإجابة لأنها لم تجتز فحص المحتوى. يُرجى إعادة صياغة السؤال.",
               "en": "The answer was withheld because it did not pass the content check. Please rephrase the question."},
}


def is_scan(hit: dict) -> bool:
    return hit.get("kind") == "scan"


async def search_scans(query: str, role: str) -> tuple[list[dict], float]:
    """Scanned passages `role` may read, and the best score among those it may not (0 if it may read everything)."""
    async def run(filters: dict | None) -> list[dict]:
        try:
            return await retrieval.search(SCAN_COLLECTION, query, k=6, candidates=24, filters=filters)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:       # corpus installed but not loaded yet: run `make ingest`
                return []
            raise
    allowed = await run({"roles": role})              # `roles` is a list; Qdrant matches any member
    if all(role in d["roles"] for d in SCANS["docs"].values()):
        return allowed, 0.0
    return allowed, max((h["rerank_score"] for h in await run(None) if role not in h["roles"]), default=0.0)


def restricted(lang: str, trace: Trace) -> dict:
    """The answer sits in a document this role may not read: say so, and return none of its content."""
    trace.add("rules", "Role-based access: the matching document is outside this role's scope")
    return {"answer": RESTRICTED[lang], "citations": [], "delta": None, "found": False, "restricted": True, "lang": lang,
            "trace": trace.to_list(), "total_ms": trace.total_ms()}


def blocked(lang: str, stage: str, trace: Trace) -> dict:
    """A guardrail stopped the question (input) or the generated answer (output): fixed reply, no sources."""
    return {"answer": BLOCKED[stage][lang], "citations": [], "delta": None, "found": False, "blocked": True, "restricted": False,
            "lang": lang, "trace": trace.to_list(), "total_ms": trace.total_ms()}


async def screen_answer(answer: str, question: str, lang: str, trace: Trace) -> tuple[str, int, bool]:
    """Guardrails on a generated answer: mask personal identifiers by rule, then the output rail.
    Returns (answer, values masked, stopped). A no-op without the scanned corpus."""
    if not SCANS:
        return answer, 0, False
    answer, masked = PII.subn(REDACTED[lang], answer)
    if masked:
        trace.add("guardrail", f"Masked {masked} personal identifier(s) in the answer (pattern rule)")
    g = await platform.guard_output(answer, user=question, config=GUARD_CONFIG)
    trace.add("guardrail", "Output guardrail (NeMo self-check)", g, g["latency_ms"])
    return answer, masked, not g["allowed"]


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
    earlier = [m["content"] for m in body.history if m.get("role") == "user"][-2:]
    # A short follow-up ("and if it's 300 thousand?") has no topic words: search with the previous question too
    query = f"{earlier[-1]} {body.question}" if earlier and len(body.question.split()) < 8 else body.question
    if SCANS and body.role not in scans.ROLE_IDS:
        raise HTTPException(400, f"role must be one of {sorted(scans.ROLE_IDS)}")
    if SCANS:
        g = await platform.guard_input(body.question, config=GUARD_CONFIG)
        trace.add("guardrail", "Input guardrail (NeMo self-check)", g, g["latency_ms"])
        if not g["allowed"]:
            return blocked(lang, "input", trace)
    hidden = 0.0
    with trace.step("retrieval", "Search procedures (bge-m3 → Qdrant → bge-reranker)") as s:
        hits = await retrieval.search(COLLECTION, query, k=6, candidates=24)
        if SCANS:
            # Same reranker and query, so scores from the two collections are comparable: keep the best six overall
            scan_hits, hidden = await search_scans(query, body.role)
            hits = sorted(hits + scan_hits, key=lambda h: -h["rerank_score"])[:6]
            s["label"] = "Search procedures and scanned documents (bge-m3 → Qdrant → bge-reranker)"
        s["detail"] = [{"title": h["title"], "page": h["page"], "lang": h["lang"], "section": h["section"], "rerank": h["rerank_score"]}
                       if is_scan(h) else
                       {"title": h["title"], "version": h["version"], "lang": h["lang"], "section": h["section"], "rerank": h["rerank_score"]}
                       for h in hits]
    best = hits[0]["rerank_score"] if hits else 0.0
    # Nothing this role may read matches well, but a document outside its scope does: no model call needed
    if hidden >= RESTRICTED_MIN > best:
        return restricted(lang, trace)
    if best < FOUND_MIN:
        msg ="لم أجد هذه المعلومة في الإجراءات المتاحة." if lang == "ar" else "I could not find this in the available procedures."
        return {"answer": msg, "citations": [], "delta": None, "trace": trace.to_list(), "found": False, "lang": lang,
                "total_ms": trace.total_ms()}

    # "What changed?" questions are answered from the version comparison, citing both versions
    if COMPARE.search(body.question) and not is_scan(hits[0]):
        proc = hits[0]["file"].split("_")[0]
        delta = await version_delta(proc, lang, trace)
        if delta:
            files = [f"{proc}_v1_ar.md", f"{proc}_v2_ar.md"]
            citations = [{"label": f"S{i + 1}", "kind": "procedure", "file": f, "title": DOCS[f]["title"], "version": DOCS[f]["version"], "lang": "ar",
                          "effective": DOCS[f]["effective"], "section": "", "text": DOCS[f]["text"][:400], "rerank": None, "cited": True}
                         for i, f in enumerate(files)]
            head = (f"التغييرات في «{delta['title']}» بين الإصدار 1 [S1] والإصدار 2 [S2]:\n\n" if lang == "ar"
                    else f"Changes in “{delta['title']}” between version 1 [S1] and version 2 [S2]:\n\n")
            answer, masked, stopped = await screen_answer(head + delta["summary"], body.question, lang, trace)
            if stopped:
                return blocked(lang, "output", trace)
            return {"answer": answer, "citations": citations, "delta": delta, "found": True, "masked": masked, "lang": lang,
                    "trace": trace.to_list(), "total_ms": trace.total_ms()}

    # Prefer the current version: if a procedure appears in both versions, put the newest first
    latest = {}
    for d in DOCS.values():
        latest[d["procedure"]] = max(latest.get(d["procedure"], 0), d["version"])
    hits.sort(key=lambda h: (not is_scan(h) and h["version"] != latest[h["procedure"]], -h["rerank_score"]))
    sources = hits[:5]
    context = "\n\n".join(f"[S{i + 1}] {h['title']} · صفحة {h['page']} · {h['section']}\n{h['text'].split(chr(10), 2)[-1]}" if is_scan(h) else
                          f"[S{i + 1}] {h['title']} · الإصدار {h['version']} (ساري من {h['effective']}) · {h['section']}\n{h['text']}"
                          for i, h in enumerate(sources))
    system = ANSWER_SYSTEM[lang] + (SCAN_NOTE[lang] if any(map(is_scan, sources)) else "")
    # Earlier QUESTIONS only (for follow-ups such as "and for credit cards?"). Earlier answers are left out:
    # with them in the prompt the model copied a previous "not found" or its citation labels.
    context_q = ("أسئلة سابقة في نفس المحادثة (للسياق فقط): " + " | ".join(earlier) + "\n") if earlier else ""
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": f"المصادر:\n{context}\n\n---\n{context_q}السؤال: {body.question}"}]
    res = await llm.chat(messages, max_tokens=700, temperature=0)
    trace.llm("Write the cited answer (workhorse)", res)

    cited = sorted({int(n) for n in re.findall(r"\[S(\d+)\]", res.text) if 0 < int(n) <= len(sources)})
    # The text shown for a scanned source gets the same identifier mask as the answer (the crop image cannot be masked)
    citations = [{"label": f"S{i + 1}", "kind": "scan", "file": h["doc_id"], "doc_id": h["doc_id"],
                  "title": h["title_en"] if lang == "en" else h["title"], "version": None, "lang": h["lang"], "effective": None,
                  "section": h["section"], "text": PII.sub(REDACTED[lang], h["display"]), "page": h["page"], "block_type": h["block_type"], "crops": h["blocks"],
                  "rerank": h["rerank_score"], "cited": (i + 1) in cited} if is_scan(h) else
                 {"label": f"S{i + 1}", "kind": "procedure", "file": h["file"], "title": h["title"], "version": h["version"], "lang": h["lang"],
                  "effective": h["effective"], "section": h["section"], "text": h["text"].split("\n", 2)[-1],
                  "rerank": h["rerank_score"], "cited": (i + 1) in cited} for i, h in enumerate(sources)]
    primary = next((c for c in citations if c["cited"]), citations[0])
    not_found = any(p in res.text for p in ("لم أجد", "could not find"))
    # The sources this role may read do not answer it, but a document outside its scope matches well
    if not_found and hidden >= RESTRICTED_MIN:
        return restricted(lang, trace)
    answer, masked, stopped = await screen_answer(res.text.strip(), body.question, lang, trace)
    if stopped:
        return blocked(lang, "output", trace)
    delta = None if primary["kind"] == "scan" else await version_delta(primary["file"].split("_")[0], lang, trace)
    return {"answer": answer, "citations": citations, "delta": None if not_found else delta, "found": not not_found,
            "restricted": False, "blocked": False, "masked": masked, "lang": lang, "trace": trace.to_list(), "total_ms": trace.total_ms()}


@app.get("/suggested")
def suggested():
    load_docs()
    # The procedure questions come from the locale pack; the first entry stays one of them (the UI walkthrough clicks it)
    return L.D2_SUGGESTED + ([
        {"lang": "ar", "q": "ما الهدف من نظام التسوية اللحظية متعدد العملات RTGS؟"},
        {"lang": "ar", "q": "ما المهلة الممنوحة لجهات منح الائتمان غير المصرفي لتوفيق أوضاعها؟"},
    ] if SCANS else [])
