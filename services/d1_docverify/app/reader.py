"""Client for the document reader (nbe-docvlm): a fine-tuned Qwen3-VL that runs on this machine.

Uploaded documents are real, so they are read only here: never through the model gateway, which on a
workstation leads to a hosted LLM. The reader applies its own prompt per document type and returns, with
every field, how sure it was. A field it was unsure of is not trusted: the officer confirms it first.
"""
import io
import json
import os
import time

import httpx
from PIL import Image, ImageOps

URL = os.getenv("DOCVLM_URL", "").rstrip("/")
TIMEOUT = float(os.getenv("DOCVLM_TIMEOUT_S", "240"))

# Document types D1 accepts, with the fields shown to the officer.
# "fields" are read by the fine-tuned adapter: (key as the reader returns it, Arabic label, English label).
# "extra" are fields the adapter was never trained to return (a letter's date, salary rows, an invoice).
# They are read by the reader's plain base model through its generic prompt, in a second call, and the screen
# says so: (name asked for, key returned, Arabic label, English label). An invoice has only such fields.
DOC_TYPES: dict[str, dict] = {
    "id_front": {"ar": "بطاقة الرقم القومي (وجه)", "en": "National ID, front", "fields": [
        ("full_name", "الاسم", "Full name"), ("national_id", "الرقم القومي", "National ID number"),
        ("birthdate_printed", "تاريخ الميلاد", "Birth date"), ("address", "العنوان", "Address")]},
    "id_back": {"ar": "بطاقة الرقم القومي (ظهر)", "en": "National ID, back", "fields": [
        ("national_id", "الرقم القومي", "National ID number"), ("expiry_date", "تاريخ الانتهاء", "Expiry date"),
        ("gender", "النوع", "Gender"), ("marital_status", "الحالة الاجتماعية", "Marital status"), ("job_title", "المهنة", "Job")]},
    "hr_letter": {"ar": "خطاب جهة العمل", "en": "HR letter", "fields": [
        ("employee_name", "اسم الموظف", "Employee name"), ("national_id", "الرقم القومي", "National ID number"),
        ("company_name", "جهة العمل", "Employer"), ("job_title", "الوظيفة", "Job title"),
        ("salary_amount", "الراتب", "Salary"), ("hire_date", "تاريخ التعيين", "Hire date"),
        ("has_stamp", "ختم", "Stamp"), ("has_signature", "توقيع", "Signature")],
        "extra": [("Letter_Date", "letter_date", "تاريخ الخطاب", "Letter date")]},
    "bank_statement": {"ar": "كشف حساب بنكي", "en": "Bank statement", "fields": [
        ("account_holder", "صاحب الحساب", "Account holder"), ("bank_name", "البنك", "Bank"), ("account_number", "رقم الحساب", "Account number"),
        ("statement_from_date", "من تاريخ", "From"), ("statement_to_date", "إلى تاريخ", "To"), ("closing_balance", "الرصيد الختامي", "Closing balance"),
        ("has_stamp", "ختم", "Stamp"), ("has_signature", "توقيع", "Signature")],
        # These names were the most reliable of four ways of asking, on 13 statements with known rows:
        # 37 of 39 salary rows right, and the paying company right on 10 of 13 (so that one is always confirmed).
        "extra": [("Salary_Transfer_Amount_1", "salary_transfer_amount_1", "تحويل راتب (1)", "Salary transfer 1"),
                  ("Salary_Transfer_Amount_2", "salary_transfer_amount_2", "تحويل راتب (2)", "Salary transfer 2"),
                  ("Salary_Transfer_Amount_3", "salary_transfer_amount_3", "تحويل راتب (3)", "Salary transfer 3"),
                  ("Salary_Transfer_Company", "salary_transfer_company", "جهة تحويل الراتب", "Salary paid by")]},
    "invoice": {"ar": "فاتورة ضريبية", "en": "Invoice", "fields": [],
                "extra": [("Customer_Name", "customer_name", "العميل", "Customer"), ("Invoice_Date", "invoice_date", "تاريخ الفاتورة", "Invoice date"),
                          ("Subtotal_Amount", "subtotal_amount", "المجموع قبل الضريبة", "Subtotal"), ("VAT_Amount", "vat_amount", "ضريبة القيمة المضافة", "VAT"),
                          ("Total_Amount", "total_amount", "الإجمالي", "Total")]},
    "utility_bill": {"ar": "فاتورة مرافق", "en": "Utility bill", "fields": [
        ("customer_name", "اسم المشترك", "Customer name"), ("address", "العنوان", "Address"),
        ("bill_date", "تاريخ الفاتورة", "Bill date"), ("amount", "المبلغ", "Amount"),
        ("utility_type", "نوع المرفق", "Utility type"), ("meter_number", "رقم العداد", "Meter number"),
        ("has_stamp", "ختم", "Stamp"), ("has_signature", "توقيع", "Signature")]},
    "electricity_bill": {"ar": "فاتورة كهرباء", "en": "Electricity bill", "fields": [
        ("customer_name", "اسم المشترك", "Customer name"), ("address", "العنوان", "Address"),
        ("bill_date", "تاريخ الفاتورة", "Bill date"), ("amount", "المبلغ", "Amount"), ("meter_number", "رقم العداد", "Meter number"),
        ("has_stamp", "ختم", "Stamp"), ("has_signature", "توقيع", "Signature")]},
    "commercial_register": {"ar": "السجل التجاري", "en": "Commercial register", "fields": [
        ("company_name", "اسم المنشأة", "Business name"), ("owner_name", "اسم المالك", "Owner name"),
        ("register_number", "رقم السجل", "Register number"), ("issue_date", "تاريخ الإصدار", "Issue date"),
        ("capital_amount", "رأس المال", "Capital"), ("has_stamp", "ختم", "Stamp"), ("has_signature", "توقيع", "Signature")]},
}


# Base-model fields that were wrong too often to stand unconfirmed, whatever confidence comes with them
ALWAYS_CONFIRM = ("salary_transfer_company",)


def configured() -> bool:
    return bool(URL)


async def health() -> dict:
    if not URL:
        return {"configured": False, "ready": False}
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.get(f"{URL}/health")
        j = r.json() if r.status_code == 200 else {}
        return {"configured": True, "ready": bool(j.get("model_loaded")), "adapter": j.get("adapter"), "base_model": j.get("base_model")}
    except Exception as exc:  # noqa: BLE001 - reported to the screen, not raised
        return {"configured": True, "ready": False, "error": type(exc).__name__}


def field_specs(doc_type: str) -> list[tuple[str, str, str, bool]]:
    """(key, Arabic label, English label, read by the base model) for every field of a type, in screen order."""
    spec = DOC_TYPES[doc_type]
    return [(k, ar, en, False) for k, ar, en in spec["fields"]] + [(k, ar, en, True) for _, k, ar, en in spec.get("extra", [])]


async def read(doc_type: str, content: bytes, extra: list | None = None) -> dict:
    """One page -> {"fields", "confidence", "doubt", "base", "ms"} or {"error", "ms"}. `doubt` lists the fields
    the reader was unsure of; `base` the fields read by the base model. `extra` overrides the type's own list."""
    spec = DOC_TYPES[doc_type]
    extra = spec.get("extra", []) if extra is None else extra
    out = await _adapter_read(doc_type, content) if spec["fields"] else {"fields": {}, "confidence": {}, "doubt": [], "ms": 0}
    if out.get("error") or not extra:
        return {**out, "base": []}
    more = await _base_read(extra, content)
    if more.get("error"):                     # the trained fields stand; the untrained ones are simply not there
        return {**out, "base": [], "ms": out["ms"] + more["ms"]} if spec["fields"] else more
    return {**out, "fields": {**out["fields"], **more["fields"]}, "confidence": {**out["confidence"], **more["confidence"]},
            "doubt": sorted(set(out["doubt"]) | set(more["doubt"]) | {k for k in ALWAYS_CONFIRM if more["fields"].get(k) not in (None, "")}),
            "base": sorted(more["fields"]), "ms": out["ms"] + more["ms"]}


async def _base_read(asks: list, content: bytes) -> dict:
    """Fields read by the plain base model. It is told to return null for what is not printed."""
    t = time.time()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(f"{URL}/extract", data={"doc_type": "document", "fields": json.dumps([a[0] for a in asks])},
                                  files={"file": ("document", content, "application/octet-stream")})
        j = r.json()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"reader unreachable ({type(exc).__name__})", "ms": int((time.time() - t) * 1000)}
    ms, data = int((time.time() - t) * 1000), j.get("data")
    if j.get("status") != "success" or not isinstance(data, dict):
        return {"error": str(j.get("message") or "the reader returned no fields")[:200], "ms": ms}
    keys = [a[1] for a in asks]
    return {"fields": {k: data.get(k) for k in keys}, "confidence": {k: v for k, v in (j.get("confidence") or {}).items() if k in keys},
            "doubt": sorted(set(j.get("low_confidence") or []) & set(keys)), "ms": ms}


async def _adapter_read(doc_type: str, content: bytes) -> dict:
    """The fields of a trained type, read with the fine-tuned adapter and the prompt it was trained with."""
    t = time.time()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(f"{URL}/extract", data={"doc_type": doc_type},
                                  files={"file": ("document", content, "application/octet-stream")})
        j = r.json()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"reader unreachable ({type(exc).__name__})", "ms": int((time.time() - t) * 1000)}
    ms = int((time.time() - t) * 1000)
    data = j.get("data")
    if j.get("status") != "success" or not isinstance(data, dict):
        return {"error": str(j.get("message") or "the reader returned no fields")[:200], "ms": ms}
    keys = [k for k, _, _ in DOC_TYPES[doc_type]["fields"]]
    fields = {k: data.get(k) for k in keys}
    confidence = {k: v for k, v in (j.get("confidence") or {}).items() if k in fields}
    if doc_type == "id_front" and "birthdate" in (j.get("confidence") or {}):
        confidence["birthdate_printed"] = j["confidence"]["birthdate"]     # the printed date; `birthdate` is derived from the number
    if data.get("national_id_confidence") is not None and "national_id" in fields:
        confidence["national_id"] = data["national_id_confidence"]
    doubt = {("birthdate_printed" if k == "birthdate" and doc_type == "id_front" else k) for k in (j.get("low_confidence") or [])}
    if data.get("national_id_unreliable"):
        doubt.add("national_id")
    return {"fields": fields, "confidence": confidence, "doubt": sorted(doubt & set(fields)),
            "partial": bool(j.get("warning")), "ms": ms}


# ---- a second reading where the first was unsure
# The reader sees a page at a fixed pixel budget, so half a page is seen at twice the detail. Measured on 90
# labelled registers and electricity bills: of 94 unsure fields, a half returned a different value with
# confidence 0.9 or more for 17, and 14 of those were right; fields right overall went from 83.1% to 85.1%.
# A half that merely repeats the first reading proved it right only 4 times in 5, so the field stays marked
# unsure either way: the second reading improves the value the officer is shown, it does not replace the officer.
SECOND_READ = os.getenv("D1_SECOND_READ", "1") == "1"
SECOND_READ_TYPES = ("hr_letter", "utility_bill", "electricity_bill", "commercial_register", "bank_statement")   # ID cards have their own path in the reader
_STRONG = 0.9


def _halves(content: bytes) -> list[bytes]:
    """The page cut in two across its longer side, with an overlap so no line is lost at the cut."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(content))).convert("RGB")
    w, h = img.size
    boxes = [(0, 0, w, int(h * 0.575)), (0, int(h * 0.425), w, h)] if h >= w else [(0, 0, int(w * 0.575), h), (int(w * 0.425), 0, w, h)]
    out = []
    for box in boxes:
        buf = io.BytesIO()
        img.crop(box).save(buf, "PNG")
        out.append(buf.getvalue())
    return out


def _same(a, b) -> bool:
    return " ".join(str(a if a is not None else "").split()).lower() == " ".join(str(b if b is not None else "").split()).lower()


async def second_read(doc_type: str, content: bytes, first: dict) -> dict:
    """`first` with unsure text fields re-read from two enlarged halves. A field changes only when one half
    (or both, agreeing) returns a different value it is confident of and no half repeats the first reading."""
    trained = {k for k, _, _ in DOC_TYPES[doc_type]["fields"]}
    unsure = [k for k in first.get("doubt", []) if k in trained and not isinstance(first["fields"].get(k), bool)]
    if not SECOND_READ or doc_type not in SECOND_READ_TYPES or first.get("error") or not unsure:
        return first
    try:
        halves = [await _adapter_read(doc_type, part) for part in _halves(content)]
    except Exception:  # noqa: BLE001 - an image that cannot be cut keeps its first reading
        return first
    halves = [h for h in halves if not h.get("error")]
    out = {**first, "fields": dict(first["fields"]), "confidence": dict(first["confidence"]), "second_read": {},
           "ms": first["ms"] + sum(h["ms"] for h in halves)}
    for key in unsure:
        was = first["fields"].get(key)
        seen = [(h["fields"].get(key), h["confidence"].get(key) or 0) for h in halves if h["fields"].get(key) not in (None, "")]
        if any(_same(v, was) for v, _ in seen):
            continue
        strong = [(v, c) for v, c in seen if c >= _STRONG]
        if len(strong) == 1 or (len(strong) == 2 and _same(strong[0][0], strong[1][0])):
            out["fields"][key], out["confidence"][key] = strong[0]
            out["second_read"][key] = was
    return out
