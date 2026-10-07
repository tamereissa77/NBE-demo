"""D1 · Doc verification for credit lending (PLAN.md §4 D1).

A loan officer opens a synthetic loan pack. For every document the system extracts fields with the
vision model, runs image forensics, then cross-checks the documents against each other and the
application. The result is evidence-backed: "flagged for review", never "fraud". A human decides.
"""
import asyncio
import difflib
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import psycopg
from fastapi import HTTPException
from fastapi.responses import FileResponse
from psycopg.rows import dict_row
from pydantic import BaseModel

from nbe_core import create_app, llm, settings
from nbe_core.audit import log_event
from nbe_core.text import normalize_ar
from nbe_core.trace import Trace
from app import forensics

DATA = Path("/data/generated/d1")
TODAY = date.fromisoformat(os.getenv("DEMO_TODAY", "2026-10-07"))
CACHE: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(_app):
    with psycopg.connect(settings.postgres_dsn, autocommit=True) as conn:
        conn.execute("""CREATE SCHEMA IF NOT EXISTS d1;
                        CREATE TABLE IF NOT EXISTS d1.decisions (applicant TEXT PRIMARY KEY, decision TEXT, note TEXT,
                            reviewer TEXT, flags INT, decided_at TIMESTAMPTZ DEFAULT now())""")
    yield


app = create_app("d1", "Doc verification for credit lending", phase="wave2")
app.router.lifespan_context = lifespan

SCHEMAS = {
    "national_id": {"name": "full name", "address": "address", "nid_masked": "masked national ID number as printed", "issue_date": "issue date YYYY-MM-DD"},
    "utility_bill": {"customer_name": "subscriber name", "address": "installation address", "account_no": "account number",
                     "period": "billing period", "amount_due": "amount due (number)"},
    "hr_letter": {"employee_name": "employee name", "nid_last4": "last 4 digits of national ID", "employer": "employer company name",
                  "job_title": "job title", "monthly_salary": "monthly salary (number)", "hire_date": "hire date YYYY-MM-DD",
                  "letter_date": "letter date YYYY-MM-DD"},
    "bank_statement": {"customer_name": "customer name", "salary_credits": "list of salary transfer rows: [{date YYYY-MM-DD, amount number, payer}]"},
    "commercial_register": {"business_name": "business name", "owner_name": "owner name", "register_no": "register number",
                            "address": "address", "expiry_date": "expiry date YYYY-MM-DD"},
    "invoice": {"customer": "customer", "subtotal": "sum of line items (number)", "vat": "VAT amount (number)", "total": "total (number)"},
}
KIND_AR = {"national_id": "بطاقة الهوية", "utility_bill": "فاتورة الكهرباء", "hr_letter": "خطاب جهة العمل", "bank_statement": "كشف الحساب",
           "commercial_register": "السجل التجاري", "invoice": "الفاتورة"}


def manifest() -> dict:
    return json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))


def applicant(aid: str) -> dict:
    for a in manifest()["applicants"]:
        if a["id"] == aid:
            return a
    raise HTTPException(404, "unknown applicant")


@app.get("/packs")
def packs():
    return [{"id": a["id"], "name_ar": a["name_ar"], "name_en": a["name_en"], "loan_amount_egp": a["loan_amount_egp"],
             "documents": [d["file"] for d in a["documents"]], "decision": _decision(a["id"]), "verified": a["id"] in CACHE}
            for a in manifest()["applicants"]]


@app.get("/doc/{file}")
def doc_image(file: str):
    p = DATA / Path(file).name
    if not p.exists():
        raise HTTPException(404, "unknown document")
    return FileResponse(p, media_type="image/jpeg")


async def extract(kind: str, path: Path) -> tuple[dict, int]:
    fields = SCHEMAS[kind]
    schema = {"type": "object", "properties": {k: ({"type": "array", "items": {"type": "object", "properties": {
        "date": {"type": "string"}, "amount": {"type": "number"}, "payer": {"type": "string"}}, "required": ["date", "amount", "payer"]}}
        if k == "salary_credits" else {"type": "number"} if "(number)" in v else {"type": "string"}) for k, v in fields.items()},
        "required": list(fields)}
    prompt = (f"This is a scanned {kind.replace('_', ' ')} (synthetic demo document, mostly Arabic). Extract these fields exactly as printed; "
              "keep Arabic text in Arabic; convert dates to YYYY-MM-DD and amounts to plain numbers:\n" +
              "\n".join(f"- {k}: {v}" for k, v in fields.items()))
    data, res = await llm.chat_json([{"role": "user", "content": [llm.image_part(forensics.full_png_b64(str(path), 1400)),
                                                                  {"type": "text", "text": prompt}]}], schema, alias="vision", max_tokens=900)
    return data, res.latency_ms


def same_name(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize_ar(a or ""), normalize_ar(b or "")).ratio()


def _date(s: str | None) -> date | None:
    try:
        return date.fromisoformat((s or "").strip()[:10].replace("/", "-"))
    except ValueError:
        return None


def cross_checks(app_rec: dict, ex: dict[str, dict]) -> list[dict]:
    """Deterministic rules across documents and the application. Each flag names the documents involved."""
    flags = []
    files = {k: f"{app_rec['id']}_{k}.jpg" for k in ex}

    def flag(rule, severity, kinds, ar, en, **evidence):
        flags.append({"source": "cross_check", "rule": rule, "severity": severity, "documents": [files[k] for k in kinds if k in files],
                      "detail_ar": ar, "detail_en": en, "evidence": evidence})

    idn = ex.get("national_id", {})
    ref_name = idn.get("name") or app_rec["name_ar"]
    for kind, key in [("utility_bill", "customer_name"), ("hr_letter", "employee_name"), ("bank_statement", "customer_name"),
                      ("commercial_register", "owner_name")]:
        if kind in ex and ex[kind].get(key):
            r = same_name(ref_name, ex[kind][key])
            if r < 0.8:
                flag("name_mismatch", "high", ["national_id", kind], f"الاسم في {KIND_AR[kind]} «{ex[kind][key]}» لا يطابق بطاقة الهوية «{ref_name}»",
                     f"Name on the {kind.replace('_', ' ')} does not match the ID card", similarity=round(r, 2))
    if "utility_bill" in ex and idn.get("address"):
        r = same_name(idn["address"], ex["utility_bill"].get("address", ""))
        if r < 0.75:
            flag("address_mismatch", "medium", ["national_id", "utility_bill"],
                 f"عنوان فاتورة المرافق «{ex['utility_bill'].get('address')}» يختلف عن عنوان بطاقة الهوية «{idn['address']}»",
                 "Utility bill address differs from the ID card address", similarity=round(r, 2))
    hr, st = ex.get("hr_letter", {}), ex.get("bank_statement", {})
    salary = hr.get("monthly_salary")
    credits = [c for c in st.get("salary_credits", []) if c.get("amount")]
    if salary and credits:
        off = [c for c in credits if abs(c["amount"] - salary) / salary > 0.15]
        if off:
            flag("salary_mismatch", "high", ["hr_letter", "bank_statement"],
                 f"الراتب في خطاب جهة العمل {salary:,.0f} جنيه، بينما إيداعات الراتب في كشف الحساب: " + "، ".join(f"{c['amount']:,.0f}" for c in credits),
                 "Salary on the HR letter differs from salary credits on the bank statement", hr_salary=salary, credits=[c["amount"] for c in credits])
    if salary and abs(salary - app_rec["declared"]["salary"]) / app_rec["declared"]["salary"] > 0.15:
        flag("declared_salary_mismatch", "medium", ["hr_letter"], f"الراتب في الخطاب {salary:,.0f} يختلف عن الراتب المذكور في الطلب {app_rec['declared']['salary']:,}",
             "HR-letter salary differs from the salary declared on the application")
    payers = {c.get("payer", "") for c in credits}
    if hr.get("employer") and payers and max(same_name(hr["employer"], p) for p in payers) < 0.7:
        flag("employer_mismatch", "high", ["hr_letter", "bank_statement"],
             f"جهة العمل في الخطاب «{hr['employer']}» لا تطابق جهة تحويل الراتب «{next(iter(payers))}»",
             "Employer on the HR letter is not the payer of the salary credits")
    ld = _date(hr.get("letter_date"))
    if ld and (ld > TODAY or (TODAY - ld).days > 90):
        flag("letter_date", "high" if ld > TODAY else "low", ["hr_letter"],
             f"تاريخ خطاب جهة العمل {ld} {'في المستقبل' if ld > TODAY else 'أقدم من 90 يوماً'}", "HR letter date is in the future" if ld > TODAY else "HR letter is older than 90 days")
    if hr.get("nid_last4") and idn.get("nid_masked") and not str(idn["nid_masked"]).strip().endswith(str(hr["nid_last4"]).strip()):
        flag("nid_mismatch", "high", ["national_id", "hr_letter"], "آخر 4 أرقام من الرقم القومي في الخطاب لا تطابق بطاقة الهوية",
             "National ID last 4 digits on the HR letter do not match the ID card")
    ex_d = _date(ex.get("commercial_register", {}).get("expiry_date"))
    if ex_d and ex_d < TODAY:
        flag("register_expired", "high", ["commercial_register"], f"السجل التجاري منتهي الصلاحية منذ {ex_d}", "Commercial register has expired")
    inv = ex.get("invoice", {})
    if inv.get("subtotal") and inv.get("total") and abs(inv["subtotal"] + (inv.get("vat") or 0) - inv["total"]) > 2:
        flag("invoice_arithmetic", "high", ["invoice"], f"إجمالي الفاتورة {inv['total']:,.0f} لا يساوي المجموع {inv['subtotal']:,.0f} + الضريبة {inv.get('vat') or 0:,.0f}",
             "Invoice total does not equal subtotal plus VAT")
    return flags


def forensic_flags(file: str, f: dict) -> list[dict]:
    out = []
    if f["noise"]["suspicious"]:
        out.append({"source": "forensics", "rule": "noise_inconsistency", "severity": "medium", "documents": [file],
                    "detail_ar": "منطقة بلا ضوضاء المسح الضوئي الموجودة في بقية الصفحة: قد تكون قيمة أعيدت كتابتها أو صورة ملصقة",
                    "detail_en": "A region lacks the scanner noise present on the rest of the page (possible re-typed value or pasted image)",
                    "evidence": {"regions": f["noise"]["regions"]}})
    if f["stamps"]["duplicate"]:
        out.append({"source": "forensics", "rule": "duplicate_stamp", "severity": "high", "documents": [file],
                    "detail_ar": f"ختمان متطابقان تقريباً (تشابه {f['stamps']['similarity']:.0%}): احتمال نسخ ولصق الختم",
                    "detail_en": "Two near-identical stamps: possible copy-move", "evidence": {"boxes": f["stamps"]["boxes"]}})
    if f["metadata"]["editor_detected"]:
        out.append({"source": "forensics", "rule": "editing_software", "severity": "medium", "documents": [file],
                    "detail_ar": f"البيانات الوصفية تشير إلى برنامج تعديل: {f['metadata']['software']}",
                    "detail_en": f"File metadata names an editing application: {f['metadata']['software']}", "evidence": f["metadata"]})
    return out


@app.post("/verify/{aid}")
async def verify(aid: str, refresh: bool = False):
    if aid in CACHE and not refresh:
        return CACHE[aid]
    a = applicant(aid)
    trace = Trace()
    sem = asyncio.Semaphore(4)

    async def one(d):
        path = DATA / d["file"]
        async with sem:
            fields, ms = await extract(d["kind"], path)
        f = {"noise": forensics.noise_inconsistency(str(path)), "stamps": forensics.duplicate_stamps(str(path)),
             "metadata": forensics.metadata(str(path)), "ela": forensics.ela(str(path))}
        return d, fields, f, ms

    results = await asyncio.gather(*(one(d) for d in a["documents"]))
    trace.add("llm", f"Extract fields from {len(results)} documents (vision: Gemma 4)", None, max(ms for *_, ms in results))
    trace.add("forensics", "Image forensics: noise consistency, duplicate stamps, metadata, ELA heatmap")
    ex = {d["kind"]: fields for d, fields, _, _ in results}
    flags = [fl for d, _, f, _ in results for fl in forensic_flags(d["file"], f)]
    cc = cross_checks(a, ex)
    trace.add("rules", f"{len(cc)} cross-document rule(s) triggered", [c["rule"] for c in cc])
    flags += cc
    order = {"high": 0, "medium": 1, "low": 2}
    flags.sort(key=lambda f: order[f["severity"]])

    docs = []
    for d, fields, f, _ in results:
        docs.append({"file": d["file"], "kind": d["kind"], "kind_ar": KIND_AR[d["kind"]], "fields": fields,
                     "flags": [fl["rule"] for fl in flags if d["file"] in fl["documents"]],
                     "forensics": {"noise": f["noise"], "stamps": f["stamps"], "metadata": f["metadata"],
                                   "ela_score": f["ela"]["score"], "image_size": f["ela"]["image_size"]},
                     "ela_heatmap": f["ela"]["heatmap_png"], "thumb": forensics.thumbnail_b64(str(DATA / d["file"]), 360)})

    verdict = "flagged_for_review" if flags else "no_issues_found"
    summary = {"ar": "لم يُعثر على مؤشرات تستدعي المراجعة.", "en": "No indicators requiring review were found."}
    if flags:
        res = await llm.chat([{"role": "user", "content":
            "اكتب ملخصاً لموظف الائتمان (3 إلى 4 جمل) بالعربية ثم بالإنجليزية تحت عنوانين AR: و EN:، يشرح لماذا أُحيل الملف للمراجعة البشرية، "
            "استناداً فقط إلى المؤشرات التالية. لا تستخدم كلمة احتيال ولا تُصدر حكماً؛ القرار للموظف.\n" +
            "\n".join(f"- [{f['severity']}] {f['detail_ar']}" for f in flags)}], max_tokens=500, temperature=0)
        trace.llm("Explain the verdict for the reviewer (workhorse)", res)
        m = re.split(r"\bEN\s*:", res.text, maxsplit=1)
        clean = lambda t: re.sub(r"\*+|^#+\s*", "", t, flags=re.M).strip()   # noqa: E731
        summary = {"ar": clean(m[0].replace("AR:", "")), "en": clean(m[1]) if len(m) > 1 else ""}

    out = {"applicant": {k: a[k] for k in ("id", "name_ar", "name_en", "loan_amount_egp", "declared")}, "verdict": verdict,
           "risk": "high" if any(f["severity"] == "high" for f in flags) else "medium" if flags else "low",
           "flags": flags, "documents": docs, "summary": summary, "decision": _decision(aid), "trace": trace.to_list(), "total_ms": trace.total_ms()}
    CACHE[aid] = out
    await log_event("verify", "vision", {"applicant": aid, "flags": len(flags)})
    return out


def _decision(aid: str) -> dict | None:
    with psycopg.connect(settings.postgres_dsn, row_factory=dict_row) as conn:
        r = conn.execute("SELECT decision, note, reviewer, decided_at FROM d1.decisions WHERE applicant=%s", (aid,)).fetchone()
    return {**r, "decided_at": r["decided_at"].isoformat()} if r else None


class DecisionIn(BaseModel):
    decision: str          # approve_docs | request_more | reject_docs
    note: str = ""
    reviewer: str = "loan officer"


@app.post("/decision/{aid}")
async def decide(aid: str, d: DecisionIn):
    if d.decision not in ("approve_docs", "request_more", "reject_docs"):
        raise HTTPException(400, "decision must be approve_docs, request_more or reject_docs")
    flags = len(CACHE.get(aid, {}).get("flags", []))
    with psycopg.connect(settings.postgres_dsn, autocommit=True) as conn:
        conn.execute("""INSERT INTO d1.decisions (applicant, decision, note, reviewer, flags) VALUES (%s,%s,%s,%s,%s)
                        ON CONFLICT (applicant) DO UPDATE SET decision=EXCLUDED.decision, note=EXCLUDED.note,
                            reviewer=EXCLUDED.reviewer, flags=EXCLUDED.flags, decided_at=now()""", (aid, d.decision, d.note, d.reviewer, flags))
    await log_event("human_decision", d.reviewer, {"applicant": aid, "decision": d.decision})
    if aid in CACHE:
        CACHE[aid]["decision"] = _decision(aid)
    return _decision(aid)


@app.post("/admin/reset")
def reset():
    CACHE.clear()
    with psycopg.connect(settings.postgres_dsn, autocommit=True) as conn:
        conn.execute("TRUNCATE d1.decisions")
    return {"reset": True}


@app.get("/evaluate")
async def evaluate():
    """Run every pack and compare flagged documents with the ground-truth manifest."""
    m = manifest()
    rows = []
    for a in m["applicants"]:
        r = await verify(a["id"])
        flagged = {f for fl in r["flags"] for f in fl["documents"]}
        for d in a["documents"]:
            rows.append({"file": d["file"], "forged": d["forged"], "manipulation": d["manipulation"],
                         "planned_false_positive": bool(d.get("planned_false_positive")), "flagged": d["file"] in flagged})
    forged = [r for r in rows if r["forged"]]
    genuine = [r for r in rows if not r["forged"]]
    return {"documents": len(rows), "forged": len(forged), "forged_flagged": sum(r["flagged"] for r in forged),
            "genuine_flagged": [r["file"] for r in genuine if r["flagged"]],
            "planned_false_positive": m["false_positive"], "missed": [r for r in forged if not r["flagged"]], "rows": rows}
