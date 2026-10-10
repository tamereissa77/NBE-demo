"""Loan files built from uploaded documents.

The officer opens a file, types what the applicant declared, uploads the documents and names each one. The
fine-tuned reader on this machine (app.reader) extracts the fields; app.rules checks them. Readings the
model was unsure of are shown as such, and the officer can correct any field and have the checks run again
without re-reading. Files and results are kept in Postgres and under UPLOADS, and deleting a file removes both.

Uploaded documents are real and personal: nothing here calls the model gateway, and neither the audit log
nor the trace carries a field value.
"""
import base64
import hashlib
import io
import os
import re
import secrets
import shutil
from datetime import date
from pathlib import Path

import psycopg
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from nbe_core import settings
from nbe_core.audit import log_event
from nbe_core.trace import Trace
from app import forensics, pdfdoc, reader, rules

UPLOADS = Path(os.getenv("D1_UPLOAD_DIR", "/data/uploads/d1"))
MAX_BYTES = int(os.getenv("D1_UPLOAD_MAX_MB", "12")) * 1024 * 1024
FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
# Image checks run on uploads, chosen by measurement on real photos with planted edits (docs/workstation.md).
# "noise", the check tuned on the generated scans, fired on 65 to 95% of untouched real photos, so it is off
# unless asked for. "patch" and "copy_move" compare a region with the camera noise around it; "recompressed"
# looks for content that missed the picture's first JPEG save. "resampled" is there but off: on the same
# benchmark it caught almost nothing (0 to 3% of planted edits) for 2 to 5% false alarms.
IMAGE_CHECKS = {c.strip() for c in os.getenv("D1_UPLOAD_FORENSICS", "metadata,stamps,copy_move,patch,recompressed").split(",")}
DECISIONS = ("approve_docs", "request_more", "reject_docs")
# The officer names the type of every document. A document stored without one (from the time the type was
# proposed automatically) is kept and waits for the officer to name it: it is not read
# and takes no part in the checks until then.
UNTYPED = "unknown"
_UNTYPED_SPEC = {"ar": "نوع غير محدد", "en": "Type not set", "fields": []}
_CASE, _DOC = re.compile(r"^C-[0-9A-F]{6}$"), re.compile(r"^[0-9a-f]{10}$")

router = APIRouter(prefix="/cases")


def init(conn: psycopg.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS d1.cases (id TEXT PRIMARY KEY, form JSONB NOT NULL, result JSONB, stale BOOLEAN DEFAULT false,
                        decision TEXT, note TEXT, reviewer TEXT, created_at TIMESTAMPTZ DEFAULT now(), decided_at TIMESTAMPTZ);
                    CREATE TABLE IF NOT EXISTS d1.case_docs (id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES d1.cases(id) ON DELETE CASCADE,
                        doc_type TEXT NOT NULL, ext TEXT NOT NULL, sha256 TEXT NOT NULL, thumb TEXT, reading JSONB, corrected JSONB DEFAULT '{}',
                        forensics JSONB, added_at TIMESTAMPTZ DEFAULT now());
                    ALTER TABLE d1.case_docs ADD COLUMN IF NOT EXISTS source JSONB""")


def _db() -> psycopg.Connection:
    return psycopg.connect(settings.postgres_dsn, autocommit=True, row_factory=dict_row)


class FormIn(BaseModel):
    applicant_name: str = ""
    national_id: str = ""
    monthly_salary: float | None = None
    employer: str = ""
    address: str = ""
    loan_amount: float | None = None
    applicant_type: str = "employee"      # employee: HR letter expected; business: commercial register expected


class FieldIn(BaseModel):
    key: str
    value: str | bool | None = None
    reset: bool = False                   # drop the officer's value and go back to what the reader returned


class TypeIn(BaseModel):
    doc_type: str


class DecisionIn(BaseModel):
    decision: str
    note: str = ""
    reviewer: str = "loan officer"


def _load(cid: str) -> tuple[dict, list[dict]]:
    if not _CASE.match(cid):
        raise HTTPException(404, "unknown file")
    with _db() as conn:
        case = conn.execute("SELECT * FROM d1.cases WHERE id=%s", (cid,)).fetchone()
        docs = conn.execute("SELECT * FROM d1.case_docs WHERE case_id=%s ORDER BY added_at", (cid,)).fetchall()
    if not case:
        raise HTTPException(404, "unknown file")
    return case, docs


def _path(cid: str, doc: dict, suffix: str = "") -> Path:
    return UPLOADS / cid / f"{doc['id']}{suffix or '.' + doc['ext']}"


def _values(doc: dict) -> dict:
    return {**(doc["reading"] or {}).get("fields", {}), **(doc["corrected"] or {})}


def _doubt(doc: dict) -> list[str]:
    """Fields the reader was unsure of and the officer has not yet confirmed or corrected."""
    return [k for k in (doc["reading"] or {}).get("doubt", []) if k not in (doc["corrected"] or {})]


def _view(case: dict, docs: list[dict]) -> dict:
    out = []
    for d in docs:
        reading, spec = d["reading"] or {}, reader.DOC_TYPES.get(d["doc_type"], _UNTYPED_SPEC)
        values, doubt = _values(d), _doubt(d)
        out.append({"id": d["id"], "doc_type": d["doc_type"], "label_ar": spec["ar"], "label_en": spec["en"], "thumb": d["thumb"],
                    "needs_type": d["doc_type"] == UNTYPED,
                    "source": d.get("source"),          # for a PDF: pages, the programs that wrote it, its dates and saves
                    "read": d["reading"] is not None, "error": reading.get("error"), "ms": reading.get("ms"),
                    "software": (d["forensics"] or {}).get("metadata", {}).get("software"), "has_ela": _path(case["id"], d, ".ela.png").exists(),
                    "size": (d["forensics"] or {}).get("size"), "boxes": _boxes(d["forensics"] or {}),
                    "noise_checkable": (d["forensics"] or {}).get("patch", {}).get("checkable"),
                    "fields": [{"key": k, "label_ar": ar, "label_en": en, "value": values.get(k), "read": reading.get("fields", {}).get(k),
                                "confidence": reading.get("confidence", {}).get(k), "doubt": k in doubt, "corrected": k in (d["corrected"] or {}),
                                "second_read": k in reading.get("second_read", {}), "base": base}     # base: read by the base model, not the trained adapter
                               for k, ar, en, base in (reader.field_specs(d["doc_type"]) if d["doc_type"] != UNTYPED else [])]
                    if d["reading"] is not None and not reading.get("error") else []})
    decision = {"decision": case["decision"], "note": case["note"], "reviewer": case["reviewer"],
                "decided_at": case["decided_at"].isoformat()} if case["decision"] else None
    return {"id": case["id"], "form": case["form"], "documents": out, "result": case["result"], "stale": bool(case["stale"]),
            "decision": decision, "created_at": case["created_at"].isoformat()}


def _boxes(f: dict) -> list[dict]:
    """Regions the image checks point at, in pixels of the upright image, for the screen to draw."""
    out = [{"bbox": r["bbox"], "kind": "patch"} for r in f.get("patch", {}).get("regions", [])]
    out += [{"bbox": r["bbox"], "kind": "resave"} for key in ("recompressed", "resampled") for r in f.get(key, {}).get("regions", [])]
    for key, kind in (("copy_move", "copy"), ("stamps", "copy")):
        if f.get(key, {}).get("duplicate"):
            out += [{"bbox": b, "kind": kind} for b in f[key]["boxes"]]
    return out


def _check(case: dict, docs: list[dict], trace: Trace | None = None) -> dict:
    """Run every check on what has been read so far and store the result. No model is called."""
    inputs = [{"id": d["id"], "doc_type": d["doc_type"], "values": _values(d), "doubt": _doubt(d),
               "error": (d["reading"] or {}).get("error"), "unread": d["reading"] is None} for d in docs if d["doc_type"] != UNTYPED]
    flags = rules.check(case["form"], inputs, date.today())
    for d in docs:
        if d["doc_type"] == UNTYPED:
            flags.append({"source": "document", "rule": "type_needed", "severity": "low", "status": "raised", "documents": [d["id"]], "confirm": [],
                          "detail_ar": "مستند لم يُحدَّد نوعه: اختر النوع ليُقرأ", "detail_en": "A document has no type yet: choose its type so it can be read", "evidence": {}})
    for d in docs:
        meta = (d["forensics"] or {}).get("metadata") or {}
        if meta.get("editor_detected"):
            flags.append({"source": "forensics", "rule": "editing_software", "severity": "medium", "status": "raised", "documents": [d["id"]], "confirm": [],
                          "detail_ar": f"البيانات الوصفية للملف تشير إلى برنامج تعديل: {meta['software']}",
                          "detail_en": f"File metadata names an editing application: {meta['software']}", "evidence": {"software": meta["software"]}})
        pdf = d.get("source") or {}
        made_by = " / ".join(x for x in (pdf.get("producer"), pdf.get("creator")) if x)
        if "pdf_editor" in pdf.get("findings", []):
            flags.append({"source": "forensics", "rule": "pdf_editor", "severity": "medium", "status": "raised", "documents": [d["id"]], "confirm": [],
                          "detail_ar": f"ملف PDF يذكر برنامج تحرير في بياناته: {made_by}", "detail_en": f"The PDF names an editing program in its own record: {made_by}",
                          "evidence": {"producer": pdf.get("producer"), "creator": pdf.get("creator")}})
        if "pdf_revisions" in pdf.get("findings", []):
            flags.append({"source": "forensics", "rule": "pdf_revisions", "severity": "medium", "status": "raised", "documents": [d["id"]], "confirm": [],
                          "detail_ar": f"ملف PDF حُفظ {pdf['revisions']} مرات فوق نسخة سابقة: أُضيف إليه شيء بعد إنشائه",
                          "detail_en": f"The PDF was saved {pdf['revisions']} times on top of an earlier version: something was added after it was made",
                          "evidence": {"revisions": pdf["revisions"]}})
        if "pdf_modified" in pdf.get("findings", []):
            flags.append({"source": "forensics", "rule": "pdf_modified", "severity": "low", "status": "raised", "documents": [d["id"]], "confirm": [],
                          "detail_ar": f"ملف PDF عُدّل بعد إنشائه (أُنشئ {pdf['created']}، عُدّل {pdf['modified']})",
                          "detail_en": f"The PDF was modified after it was created (created {pdf['created']}, modified {pdf['modified']})",
                          "evidence": {"created": pdf["created"], "modified": pdf["modified"]}})
        f = d["forensics"] or {}
        if f.get("stamps", {}).get("duplicate"):
            flags.append({"source": "forensics", "rule": "duplicate_stamp", "severity": "high", "status": "raised", "documents": [d["id"]], "confirm": [],
                          "detail_ar": "ختمان متطابقان تقريباً في المستند: احتمال نسخ ولصق الختم", "detail_en": "Two near-identical stamps: possible copy-move",
                          "evidence": {"boxes": f["stamps"]["boxes"]}})
        if f.get("copy_move", {}).get("duplicate"):
            flags.append({"source": "forensics", "rule": "copied_region", "severity": "high", "status": "raised", "documents": [d["id"]], "confirm": [],
                          "detail_ar": "منطقة في الصورة مطابقة تماماً لمنطقة أخرى فيها: احتمال نسخ ولصق داخل المستند",
                          "detail_en": "One region of the image is an exact copy of another: possible copy and paste within the document",
                          "evidence": {"boxes": f["copy_move"]["boxes"], "blocks": f["copy_move"]["blocks"]}})
        if f.get("patch", {}).get("suspicious"):
            flags.append({"source": "forensics", "rule": "pasted_patch", "severity": "medium", "status": "raised", "documents": [d["id"]], "confirm": [],
                          "detail_ar": "كتابة على مساحة بلا ضوضاء التصوير الموجودة حولها: احتمال قيمة أعيدت كتابتها فوق الصورة",
                          "detail_en": "Writing on a patch that lacks the camera noise around it: possibly a value typed over the photo",
                          "evidence": {"regions": f["patch"]["regions"]}})
        if f.get("recompressed", {}).get("suspicious"):
            flags.append({"source": "forensics", "rule": "added_after_first_save", "severity": "medium", "status": "raised", "documents": [d["id"]], "confirm": [],
                          "detail_ar": "منطقة لا تحمل أثر الحفظ الأول للصورة الموجود في بقيتها: احتمال محتوى أُضيف ثم أُعيد حفظ الصورة",
                          "detail_en": "A region lacks the trace of the picture's first save that the rest of it has: possibly content added before it was saved again",
                          "evidence": {"regions": f["recompressed"]["regions"], "first_quality": f["recompressed"].get("first_quality")}})
        if f.get("resampled", {}).get("suspicious"):
            flags.append({"source": "forensics", "rule": "resized_region", "severity": "low", "status": "raised", "documents": [d["id"]], "confirm": [],
                          "detail_ar": "منطقة تحمل أثر تغيير الحجم دون بقية الصورة", "detail_en": "A region shows the trace of resizing that the rest of the picture does not",
                          "evidence": {"regions": f["resampled"]["regions"]}})
        if f.get("noise", {}).get("suspicious"):
            flags.append({"source": "forensics", "rule": "noise_inconsistency", "severity": "medium", "status": "raised", "documents": [d["id"]], "confirm": [],
                          "detail_ar": "منطقة بلا ضوضاء التصوير الموجودة في بقية الصفحة", "detail_en": "A region lacks the capture noise present on the rest of the page",
                          "evidence": {"regions": f["noise"]["regions"]}})
    order = {"high": 0, "medium": 1, "low": 2}
    flags.sort(key=lambda f: (f["status"] != "raised", order[f["severity"]]))
    outcome, risk = rules.verdict(flags)
    if trace is not None:
        trace.add("rules", f"{len(flags)} check(s) raised or awaiting confirmation", [f["rule"] for f in flags])
    previous = case["result"] or {}
    result = {"verdict": outcome, "risk": risk, "flags": flags, "summary": rules.summarise(flags, outcome),
              "trace": trace.to_list() if trace is not None else previous.get("trace", []),
              "total_ms": trace.total_ms() if trace is not None else previous.get("total_ms", 0), "checked_on": date.today().isoformat()}
    with _db() as conn:
        conn.execute("UPDATE d1.cases SET result=%s, stale=false WHERE id=%s", (Jsonb(result), case["id"]))
    return result


def _image_checks(path: Path) -> dict:
    out = {"metadata": forensics.metadata(str(path))}
    try:
        out["size"] = list(ImageOps.exif_transpose(Image.open(path)).size)
        if "stamps" in IMAGE_CHECKS:
            out["stamps"] = forensics.duplicate_stamps(str(path))
        if "copy_move" in IMAGE_CHECKS:
            out["copy_move"] = forensics.copy_move(str(path))
        if "patch" in IMAGE_CHECKS:
            out["patch"] = forensics.pasted_patch(str(path))
        if "recompressed" in IMAGE_CHECKS and path.suffix == ".jpg":
            out["recompressed"] = forensics.recompressed(str(path))
        if "resampled" in IMAGE_CHECKS:
            out["resampled"] = forensics.resampled(str(path))
        if "noise" in IMAGE_CHECKS:
            out["noise"] = forensics.noise_inconsistency(str(path))
        if path.suffix == ".jpg":            # error levels only mean something for a JPEG
            ela = forensics.ela(str(path))
            path.with_name(path.stem + ".ela.png").write_bytes(base64.b64decode(ela["heatmap_png"]))
            out["ela_score"] = ela["score"]
    except Exception as exc:  # noqa: BLE001 - an image a check cannot open is reported, the file is still verified
        out["error"] = type(exc).__name__
    return out


@router.get("/reader")
async def reader_status():
    """Whether uploaded documents can be read here, for the screen to say so before anyone uploads."""
    return {**await reader.health(),
            "doc_types": [{"id": k, "ar": v["ar"], "en": v["en"]} for k, v in reader.DOC_TYPES.items()]}


@router.get("")
def list_cases():
    with _db() as conn:
        rows = conn.execute("""SELECT c.id, c.form->>'applicant_name' AS applicant_name, c.form->>'loan_amount' AS loan_amount,
                                      c.result->>'verdict' AS verdict, c.decision, c.created_at, count(d.id) AS documents
                               FROM d1.cases c LEFT JOIN d1.case_docs d ON d.case_id = c.id GROUP BY c.id ORDER BY c.created_at DESC""").fetchall()
    return [{**r, "created_at": r["created_at"].isoformat()} for r in rows]


@router.post("")
async def create_case(form: FormIn):
    cid = "C-" + secrets.token_hex(3).upper()
    with _db() as conn:
        conn.execute("INSERT INTO d1.cases (id, form) VALUES (%s, %s)", (cid, Jsonb(form.model_dump())))
    await log_event("case_opened", "loan officer", {"case": cid})
    return _view(*_load(cid))


@router.get("/{cid}")
def get_case(cid: str):
    return _view(*_load(cid))


@router.put("/{cid}/form")
def update_form(cid: str, form: FormIn):
    case, docs = _load(cid)
    with _db() as conn:
        conn.execute("UPDATE d1.cases SET form=%s WHERE id=%s", (Jsonb(form.model_dump()), cid))
    if case["result"]:
        _check({**case, "form": form.model_dump()}, docs)
    return _view(*_load(cid))


@router.delete("/{cid}")
async def delete_case(cid: str):
    """Remove the file, its documents and its results from this machine."""
    _load(cid)
    with _db() as conn:
        conn.execute("DELETE FROM d1.cases WHERE id=%s", (cid,))
    shutil.rmtree(UPLOADS / cid, ignore_errors=True)
    await log_event("case_deleted", "loan officer", {"case": cid})
    return {"deleted": cid}


@router.post("/{cid}/documents")
async def add_document(cid: str, doc_type: str = Form(...), file: UploadFile = File(...)):
    _load(cid)
    if doc_type not in reader.DOC_TYPES:        # the officer says what the document is; nothing guesses it
        raise HTTPException(400, f"doc_type must be one of: {', '.join(reader.DOC_TYPES)}")
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(413, f"the image is larger than {MAX_BYTES // (1024 * 1024)} MB")
    source, original = None, None
    if pdfdoc.is_pdf(content):                 # a PDF: its own record is checked, and its first page becomes the image that is read
        try:
            source, original = pdfdoc.inspect(content), content
            content, source["pages"] = pdfdoc.render(content)
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "the PDF could not be opened") from None
    try:                                       # the type is decided from the bytes, never from the uploaded name
        fmt = Image.open(io.BytesIO(content)).format
        Image.open(io.BytesIO(content)).verify()
        thumb = ImageOps.exif_transpose(Image.open(io.BytesIO(content))).convert("RGB")
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "the file is not a readable image") from None
    if fmt not in FORMATS:
        raise HTTPException(400, "upload a JPEG, PNG or WebP image of the document, or a PDF")
    did = secrets.token_hex(5)
    doc = {"id": did, "ext": FORMATS[fmt]}
    (UPLOADS / cid).mkdir(parents=True, exist_ok=True)
    _path(cid, doc).write_bytes(content)       # stored under an id, not under the name it arrived with
    if original is not None:
        _path(cid, doc, ".src.pdf").write_bytes(original)
    thumb.thumbnail((360, 540))
    buf = io.BytesIO()
    thumb.save(buf, "JPEG", quality=80)
    with _db() as conn:
        conn.execute("INSERT INTO d1.case_docs (id, case_id, doc_type, ext, sha256, thumb, source) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                     (did, cid, doc_type, FORMATS[fmt], hashlib.sha256(original or content).hexdigest(), base64.b64encode(buf.getvalue()).decode(),
                      Jsonb(source) if source else None))
        conn.execute("UPDATE d1.cases SET stale = (result IS NOT NULL) WHERE id=%s", (cid,))
    return _view(*_load(cid))


def _doc(cid: str, did: str) -> tuple[dict, list[dict], dict]:
    case, docs = _load(cid)
    doc = next((d for d in docs if d["id"] == did), None) if _DOC.match(did) else None
    if not doc:
        raise HTTPException(404, "unknown document")
    return case, docs, doc


@router.delete("/{cid}/documents/{did}")
def remove_document(cid: str, did: str):
    case, _, doc = _doc(cid, did)
    with _db() as conn:
        conn.execute("DELETE FROM d1.case_docs WHERE id=%s", (did,))
    for p in (_path(cid, doc), _path(cid, doc, ".ela.png"), _path(cid, doc, ".src.pdf")):
        p.unlink(missing_ok=True)
    case, docs = _load(cid)
    if case["result"]:
        _check(case, docs)
    return _view(*_load(cid))


@router.post("/{cid}/documents/{did}/type")
def set_type(cid: str, did: str, t: TypeIn):
    """The officer changes what a document is. A new type means a new reading."""
    case, _, doc = _doc(cid, did)
    if t.doc_type not in reader.DOC_TYPES:
        raise HTTPException(400, f"doc_type must be one of: {', '.join(reader.DOC_TYPES)}")
    with _db() as conn:
        if t.doc_type != doc["doc_type"]:
            conn.execute("UPDATE d1.case_docs SET doc_type=%s, reading=NULL, corrected='{}' WHERE id=%s", (t.doc_type, did))
            conn.execute("UPDATE d1.cases SET stale = (result IS NOT NULL) WHERE id=%s", (cid,))
    return _view(*_load(cid))


@router.get("/{cid}/documents/{did}/image")
def document_image(cid: str, did: str, ela: bool = False):
    _, _, doc = _doc(cid, did)
    path = _path(cid, doc, ".ela.png" if ela else "")
    if not path.exists():
        raise HTTPException(404, "no such image")
    return FileResponse(path, headers={"Cache-Control": "private, no-store"})


@router.post("/{cid}/verify")
async def verify(cid: str, refresh: bool = False):
    """Read every document that has not been read yet (all of them with refresh), then run the checks."""
    case, docs = _load(cid)
    if not docs:
        raise HTTPException(400, "upload at least one document first")
    state = await reader.health()
    if not state["configured"]:
        raise HTTPException(503, "The document reader is not part of this installation: only the demo packs can be verified here.")
    if not state["ready"]:
        raise HTTPException(503, "The document reader is still loading its model. Try again in a minute.")
    trace = Trace()
    if all(d["doc_type"] == UNTYPED for d in docs):
        raise HTTPException(409, "choose the type of each document first")
    for d in docs:
        if d["doc_type"] == UNTYPED or (d["reading"] is not None and not d["reading"].get("error") and not refresh):
            continue
        path = _path(cid, d)
        content = path.read_bytes()
        res = await reader.read(d["doc_type"], content)
        trace.add("llm", f"Read {reader.DOC_TYPES[d['doc_type']]['en']} (fine-tuned Qwen3-VL on this machine)",
                  {"error": res["error"]} if res.get("error") else
                  {"fields": len(res["fields"]), "unsure": len(res["doubt"]), "read_by_base_model": len(res.get("base", []))}, res["ms"])
        again = await reader.second_read(d["doc_type"], content, res)
        if again is not res:
            trace.add("llm", f"Second reading of {reader.DOC_TYPES[d['doc_type']]['en']} in two enlarged halves, for the unsure fields",
                      {"fields_changed": len(again["second_read"])}, again["ms"] - res["ms"])
            res = again
        with trace.step("forensics", "Image checks: " + ", ".join(sorted(IMAGE_CHECKS)) + ", error-level picture"):
            checks = _image_checks(path)
        with _db() as conn:
            conn.execute("UPDATE d1.case_docs SET reading=%s, forensics=%s, corrected='{}' WHERE id=%s", (Jsonb(res), Jsonb(checks), d["id"]))
    case, docs = _load(cid)
    result = _check(case, docs, trace)
    await log_event("verify", "docvlm", {"case": cid, "documents": len(docs), "flags": len(result["flags"]), "verdict": result["verdict"]},
                    latency_ms=result["total_ms"])
    return _view(*_load(cid))


@router.post("/{cid}/documents/{did}/fields")
async def correct_field(cid: str, did: str, f: FieldIn):
    """The officer confirms or corrects one field; the checks run again on the new value."""
    case, docs, doc = _doc(cid, did)
    if doc["reading"] is None or f.key not in {k for k, *_ in reader.field_specs(doc["doc_type"])}:
        raise HTTPException(400, "unknown field")
    corrected = dict(doc["corrected"] or {})
    if f.reset:
        corrected.pop(f.key, None)
    else:
        corrected[f.key] = f.value.strip() if isinstance(f.value, str) else f.value
    with _db() as conn:
        conn.execute("UPDATE d1.case_docs SET corrected=%s WHERE id=%s", (Jsonb(corrected), did))
    await log_event("field_reset" if f.reset else "field_confirmed", "loan officer", {"case": cid, "document": doc["doc_type"], "field": f.key})
    case, docs = _load(cid)
    _check(case, docs)
    return _view(*_load(cid))


@router.post("/{cid}/decision")
async def decide(cid: str, d: DecisionIn):
    if d.decision not in DECISIONS:
        raise HTTPException(400, f"decision must be one of: {', '.join(DECISIONS)}")
    _load(cid)
    with _db() as conn:
        conn.execute("UPDATE d1.cases SET decision=%s, note=%s, reviewer=%s, decided_at=now() WHERE id=%s", (d.decision, d.note, d.reviewer, cid))
    await log_event("human_decision", d.reviewer, {"case": cid, "decision": d.decision})
    return _view(*_load(cid))
