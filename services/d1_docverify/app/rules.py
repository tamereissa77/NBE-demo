"""Checks on an uploaded loan file: each document against itself, the documents against each other, and
against what the applicant declared. Deterministic: no model and no I/O, so tests/d1_rules.py runs them alone.

A check can only be as good as the reading under it. When a mismatch rests on a field the reader was
unsure of, the flag is not raised as a finding: it asks the officer to confirm the reading first
(status "needs_confirmation"), so a misread letter does not look like a forged document.
"""
import difflib
import re
from datetime import date

from nbe_core import locale as L
from nbe_core.text import normalize_ar
from app import nid

NAME_MATCH = 0.70          # two names are the same person at or above this share of matching name parts
ADDRESS_MATCH = 0.50
EMPLOYER_MATCH = 0.60
SALARY_TOLERANCE = 0.15
BILL_MAX_AGE_DAYS = 92
LETTER_MAX_AGE_DAYS = 90
SALARY_CREDITS = ("salary_transfer_amount_1", "salary_transfer_amount_2", "salary_transfer_amount_3")

LABEL = {"id_front": (f"{L.ID_CARD_AR} (وجه)", "ID card front"), "id_back": (f"{L.ID_CARD_AR} (ظهر)", "ID card back"),
         "hr_letter": ("خطاب جهة العمل", "HR letter"), "utility_bill": ("فاتورة المرافق", "utility bill"),
         "electricity_bill": ("فاتورة الكهرباء", "electricity bill"), "commercial_register": ("السجل التجاري", "commercial register"),
         "bank_statement": ("كشف الحساب", "bank statement"), "invoice": ("الفاتورة الضريبية", "invoice"),
         "form": ("طلب القرض", "application")}
BILLS = ("electricity_bill", "utility_bill")
_HONORIFICS = {"السيد", "السيده", "الاستاذ", "الاستاذه", "الدكتور", "الدكتوره", "المهندس", "المهندسه", "الحاج", "الحاجه",
               "mr", "mrs", "ms", "miss", "dr", "eng"}
_PLACE_WORDS = {"شارع", "ش", "رقم", "عماره", "عقار", "شقه", "الدور", "محافظه", "مركز", "قسم", "مدينه", "حي", "منطقه", "برج",
                "st", "street", "no", "building", "apt", "floor"}
_COMPANY_WORDS = {"شركه", "مؤسسه", "مجموعه", "مصنع", "ش", "م", "co", "company", "group", "ltd", "llc", "inc", "sae"}
_AR, _LATIN = re.compile(r"[؀-ۿ]"), re.compile(r"[A-Za-z]")


def _script(text: str) -> str:
    return "ar" if len(_AR.findall(text)) >= len(_LATIN.findall(text)) else "en"


def _tokens(text, drop: set[str] = frozenset(), digits: bool = True) -> list[str]:
    text = normalize_ar(str(text or "")).translate(nid.AR_DIGITS).lower()
    text = re.sub(r"[^\w\s]|_", " ", text)
    if not digits:
        text = re.sub(r"\d+", " ", text)
    return [t for t in text.split() if t not in drop]


def _name_parts(text) -> list[str]:
    """Name parts, with compound names written as one part: «عبد الرحمن» and «عبدالرحمن» are the same name."""
    out, glue = [], False
    for t in _tokens(text, _HONORIFICS, digits=False):
        if glue and out:
            out[-1] += t
        else:
            out.append(t)
        glue = t in ("عبد", "ابو", "ام", "abd", "abu", "abdel", "el", "al")
    return out


def _same(a: str, b: str) -> bool:
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def _in_order(a: list[str], b: list[str]) -> int:
    """Longest run of parts that appear in both, in the same order (parts match when nearly equal)."""
    row = [0] * (len(b) + 1)
    for x in a:
        prev = 0
        for j, y in enumerate(b, 1):
            cur = row[j]
            row[j] = prev + 1 if _same(x, y) else max(row[j], row[j - 1])
            prev = cur
    return row[-1]


def name_similarity(a, b) -> float | None:
    """0 to 1, or None when the two cannot be compared (one is empty, or one is Arabic and the other Latin).
    A shorter name contained in a longer one counts as the same person; a different first name does not."""
    pa, pb = _name_parts(a), _name_parts(b)
    if not pa or not pb or _script(" ".join(pa)) != _script(" ".join(pb)):
        return None
    score = _in_order(pa, pb) / min(len(pa), len(pb))
    if not _same(pa[0], pb[0]):
        score = min(score, 0.5)
    if min(len(pa), len(pb)) < 2:
        score = min(score, 0.6)          # one name part is not enough to say it is the same person
    return round(score, 2)


def text_similarity(a, b, drop: set[str], digits: bool = True) -> float | None:
    """Share of the shorter text's words found in the other (addresses, company names). None: not comparable."""
    ta, tb = _tokens(a, drop, digits), _tokens(b, drop, digits)
    if not ta or not tb or _script(" ".join(ta)) != _script(" ".join(tb)):
        return None
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return round(sum(any(_same(x, y) for y in long_) for x in short) / len(short), 2)


def number(value) -> float | None:
    text = re.sub(r"[^\d.]", "", str(value if value is not None else "").translate(nid.AR_DIGITS))
    try:
        return float(text) if text.strip(".") else None
    except ValueError:
        return None


def parse_date(value) -> date | None:
    text = str(value or "").translate(nid.AR_DIGITS)
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    parts = [int(g) for g in m.groups()] if m else None
    if not parts:
        m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", text)
        parts = [int(g) for g in reversed(m.groups())] if m else None
    try:
        return date(*parts) if parts else None
    except ValueError:
        return None


def check(form: dict, docs: list[dict], today: date) -> list[dict]:
    """docs: [{"id", "doc_type", "values": {field: value}, "doubt": [fields the reader was unsure of], "error", "unread"}].
    A document uploaded but not read yet ("unread") counts as present and is checked after it is read.
    Returns flags: findings first, most severe first."""
    flags: list[dict] = []
    by: dict[str, dict] = {}
    uploaded, docs = docs, [d for d in docs if not d.get("unread")]
    for d in docs:
        if not d.get("error"):
            by.setdefault(d["doc_type"], d)
    declared = {"id": "form", "doc_type": "form", "values": form, "doubt": []}

    def val(doc, key):
        v = (doc or {}).get("values", {}).get(key)
        return v if v not in (None, "") else None

    def flag(rule, severity, ar, en, used, source="cross_check", **evidence):
        """used: [(doc, field)] the check read. Fields among them that the reader doubted need confirming first."""
        involved = [d for d, _ in used if d["id"] != "form"]
        confirm = [{"document": d["id"], "field": k} for d, k in used if k in d.get("doubt", [])]
        flags.append({"source": source, "rule": rule, "severity": severity, "status": "needs_confirmation" if confirm else "raised",
                      "documents": list(dict.fromkeys(d["id"] for d in involved)), "confirm": confirm,
                      "detail_ar": ar, "detail_en": en, "evidence": evidence})

    def where(doc, lang):
        return LABEL[doc["doc_type"]][0 if lang == "ar" else 1]

    # ---- every document on its own
    for d in docs:
        if d.get("error"):
            flag("unreadable_document", "medium", f"تعذرت قراءة {where(d, 'ar')}", f"The {where(d, 'en')} could not be read",
                 [(d, "")], source="document")
    for kind in ("id_front", "id_back", "hr_letter"):
        d = by.get(kind)
        if d and (val(d, "national_id") is not None or kind != "hr_letter"):
            _, problems = nid.inspect(val(d, "national_id"))
            if problems:
                flag("id_number_invalid", "high", f"{L.NATIONAL_ID_AR} في {where(d, 'ar')} غير صحيح: " + "؛ ".join(p[0] for p in problems),
                     f"The national ID number on the {where(d, 'en')} is not a valid number: " + "; ".join(p[1] for p in problems),
                     [(d, "national_id")], source="document")
    front, back, hr, reg = by.get("id_front"), by.get("id_back"), by.get("hr_letter"), by.get("commercial_register")
    bill = next((by[k] for k in BILLS if k in by), None)
    statement, invoice = by.get("bank_statement"), by.get("invoice")

    facts_front, _ = nid.inspect(val(front, "national_id")) if front else (None, [])
    facts_back, _ = nid.inspect(val(back, "national_id")) if back else (None, [])
    printed = parse_date(val(front, "birthdate_printed"))
    if facts_front and printed and printed.isoformat() != facts_front["birthdate"]:
        flag("id_birthdate_mismatch", "medium", f"تاريخ الميلاد المطبوع على البطاقة ({printed}) يختلف عن التاريخ داخل {L.NATIONAL_ID_AR} ({facts_front['birthdate']})",
             "The birth date printed on the card differs from the date inside its own national ID number",
             [(front, "national_id"), (front, "birthdate_printed")], source="document", printed=str(printed), in_number=facts_front["birthdate"])
    gender = str(val(back, "gender") or "")
    if facts_back and gender and normalize_ar(gender) != normalize_ar(facts_back["gender"]):
        flag("id_gender_mismatch", "medium", f"النوع المطبوع على ظهر البطاقة ({gender}) يختلف عن النوع داخل {L.NATIONAL_ID_AR} ({facts_back['gender']})",
             "The gender printed on the card differs from the gender inside its own national ID number",
             [(back, "national_id"), (back, "gender")], source="document")
    expiry = parse_date(val(back, "expiry_date"))
    if back and expiry and expiry < today:
        flag("id_expired", "high", f"{L.ID_CARD_AR} منتهية منذ {expiry}", f"The national ID card expired on {expiry}",
             [(back, "expiry_date")], source="document", expiry=str(expiry))
    for d, label in ((hr, "خطاب جهة العمل"), (reg, "السجل التجاري")):
        if d and val(d, "has_stamp") is False:
            flag("missing_stamp", "medium", f"{label} بلا ختم", f"The {where(d, 'en')} carries no stamp", [(d, "has_stamp")], source="document")
    if hr and val(hr, "has_signature") is False:
        flag("missing_signature", "medium", "خطاب جهة العمل بلا توقيع", "The HR letter carries no signature", [(hr, "has_signature")], source="document")
    hired = parse_date(val(hr, "hire_date"))
    if hr and hired and hired > today:
        flag("hire_date_future", "high", f"تاريخ التعيين في خطاب جهة العمل ({hired}) في المستقبل", "The hire date on the HR letter is in the future",
             [(hr, "hire_date")], source="document")
    billed = parse_date(val(bill, "bill_date"))
    if bill and billed and (billed > today or (today - billed).days > BILL_MAX_AGE_DAYS):
        future = billed > today
        flag("bill_date", "high" if future else "low", f"تاريخ {where(bill, 'ar')} ({billed}) " + ("في المستقبل" if future else "أقدم من ثلاثة أشهر"),
             f"The {where(bill, 'en')} date is " + ("in the future" if future else "older than three months"), [(bill, "bill_date")], source="document")

    lettered = parse_date(val(hr, "letter_date"))
    if hr and lettered and (lettered > today or (today - lettered).days > LETTER_MAX_AGE_DAYS):
        future = lettered > today
        flag("letter_date", "high" if future else "low", f"تاريخ خطاب جهة العمل ({lettered}) " + ("في المستقبل" if future else "أقدم من 90 يوماً"),
             "The HR letter is dated " + ("in the future" if future else "more than 90 days ago"), [(hr, "letter_date")], source="document")
    ended = parse_date(val(statement, "statement_to_date"))
    if statement and ended and (ended > today or (today - ended).days > BILL_MAX_AGE_DAYS):
        future = ended > today
        flag("statement_date", "high" if future else "low", f"نهاية فترة كشف الحساب ({ended}) " + ("في المستقبل" if future else "أقدم من ثلاثة أشهر"),
             "The bank statement ends " + ("in the future" if future else "more than three months ago"), [(statement, "statement_to_date")], source="document")
    sub, vat, total = (number(val(invoice, k)) for k in ("subtotal_amount", "vat_amount", "total_amount"))
    if invoice and sub and total and abs(sub + (vat or 0) - total) > max(2, 0.005 * total):
        flag("invoice_arithmetic", "high", f"إجمالي الفاتورة {total:,.0f} لا يساوي المجموع {sub:,.0f} + الضريبة {vat or 0:,.0f}",
             "The invoice total does not equal the subtotal plus VAT",
             [(invoice, "subtotal_amount"), (invoice, "vat_amount"), (invoice, "total_amount")], source="document", subtotal=sub, vat=vat, total=total)

    # ---- the documents against each other and against the application
    if front and back and nid.complete(val(front, "national_id")) and nid.complete(val(back, "national_id")):
        n = nid.differing(val(front, "national_id"), val(back, "national_id"))
        if n:
            flag("id_sides_mismatch", "high", f"{L.NATIONAL_ID_AR} على وجه البطاقة يختلف عن ظهرها في {n} رقم", f"The ID number on the front differs from the back in {n} digit(s)",
                 [(front, "national_id"), (back, "national_id")], differing_digits=n)
    ref_id = next((d for d in (front, back) if d and nid.complete(val(d, "national_id"))), None)
    for other in (hr, declared):
        theirs = val(other, "national_id")
        if ref_id and other and nid.complete(theirs):
            n = nid.differing(val(ref_id, "national_id"), theirs)
            if n:
                flag("nid_mismatch", "high", f"{L.NATIONAL_ID_AR} في {where(other, 'ar')} يختلف عن {L.ID_CARD_AR} في {n} رقم",
                     f"The national ID number on the {where(other, 'en')} differs from the ID card in {n} digit(s)",
                     [(ref_id, "national_id"), (other, "national_id")], differing_digits=n)

    ref_name = (front, "full_name") if val(front, "full_name") else (declared, "applicant_name") if val(declared, "applicant_name") else None
    for other, key, severity in ((hr, "employee_name", "high"), (reg, "owner_name", "high"), (statement, "account_holder", "high"),
                                 (bill, "customer_name", "medium"), (declared, "applicant_name", "high")):
        if not ref_name or not other or other is ref_name[0] or val(other, key) is None:
            continue
        mine, theirs = val(*ref_name), val(other, key)
        s = name_similarity(mine, theirs)
        if s is None:
            flags.append({"source": "cross_check", "rule": "name_not_comparable", "severity": "low", "status": "needs_confirmation",
                          "documents": [d["id"] for d in (ref_name[0], other) if d["id"] != "form"], "confirm": [],
                          "detail_ar": f"الاسم في {where(other, 'ar')} «{theirs}» مكتوب بحروف مختلفة عن {where(ref_name[0], 'ar')} «{mine}»: يقارنه الموظف",
                          "detail_en": f"The name on the {where(other, 'en')} is in a different script from the {where(ref_name[0], 'en')}: the officer compares them",
                          "evidence": {}})
        elif s < NAME_MATCH:
            flag("name_mismatch", severity, f"الاسم في {where(other, 'ar')} «{theirs}» لا يطابق {where(ref_name[0], 'ar')} «{mine}»",
                 f"The name on the {where(other, 'en')} does not match the {where(ref_name[0], 'en')}",
                 [ref_name, (other, key)], similarity=s)

    # The ID card's address is the reference; a file without the card is checked against the declared address
    ref_addr = (front, "address") if val(front, "address") else (declared, "address") if val(declared, "address") else None
    for other, severity in ((bill, "medium"), (declared, "low")):
        if ref_addr and other and other is not ref_addr[0] and val(other, "address"):
            s = text_similarity(val(*ref_addr), val(other, "address"), _PLACE_WORDS)
            if s is not None and s < ADDRESS_MATCH:
                flag("address_mismatch", severity,
                     f"العنوان في {where(other, 'ar')} «{val(other, 'address')}» يختلف عن العنوان في {where(ref_addr[0], 'ar')} «{val(*ref_addr)}»",
                     f"The address on the {where(other, 'en')} differs from the address on the {where(ref_addr[0], 'en')}",
                     [ref_addr, (other, "address")], similarity=s)

    salary, stated = number(val(hr, "salary_amount")), number(val(declared, "monthly_salary"))
    if hr and salary and stated and abs(salary - stated) / stated > SALARY_TOLERANCE:
        flag("salary_mismatch", "high", f"الراتب في خطاب جهة العمل {salary:,.0f} {L.CURRENCY_AR} يختلف عن الراتب المذكور في الطلب {stated:,.0f} {L.CURRENCY_AR}",
             "The salary on the HR letter differs from the salary declared on the application", [(hr, "salary_amount")], letter=salary, declared=stated)
    if hr and val(hr, "company_name") and val(declared, "employer"):
        s = text_similarity(val(hr, "company_name"), val(declared, "employer"), _COMPANY_WORDS, digits=False)
        if s is not None and s < EMPLOYER_MATCH:
            flag("employer_mismatch", "medium", f"جهة العمل في الخطاب «{val(hr, 'company_name')}» تختلف عن المذكورة في الطلب «{val(declared, 'employer')}»",
                 "The employer on the HR letter differs from the employer declared on the application", [(hr, "company_name")], similarity=s)

    # The salary letter against the money that actually arrived: the check a forged letter cannot pass by itself
    paid = [k for k in SALARY_CREDITS if number(val(statement, k))]
    credits = [number(val(statement, k)) for k in paid]
    if hr and salary and credits and any(abs(c - salary) / salary > SALARY_TOLERANCE for c in credits):
        flag("salary_vs_statement", "high", f"الراتب في خطاب جهة العمل {salary:,.0f} {L.CURRENCY_AR}، بينما إيداعات الراتب في كشف الحساب: " + "، ".join(f"{c:,.0f}" for c in credits),
             "The salary on the HR letter differs from the salary credits on the bank statement",
             [(hr, "salary_amount")] + [(statement, k) for k in paid], letter=salary, credits=credits)
    elif len(credits) > 1 and max(credits) / min(credits) > 1 + 2 * SALARY_TOLERANCE:
        flag("salary_credits_vary", "medium", "إيداعات الراتب في كشف الحساب غير متساوية: " + "، ".join(f"{c:,.0f}" for c in credits),
             "The salary credits on the bank statement differ from one another", [(statement, k) for k in paid], credits=credits)
    payer = val(statement, "salary_transfer_company")
    for other, key, severity in ((hr, "company_name", "high"), (declared, "employer", "medium")):
        if payer and other and val(other, key):
            s = text_similarity(payer, val(other, key), _COMPANY_WORDS, digits=False)
            if s is not None and s < EMPLOYER_MATCH:
                flag("payer_mismatch", severity, f"جهة تحويل الراتب في كشف الحساب «{payer}» تختلف عن جهة العمل في {where(other, 'ar')} «{val(other, key)}»",
                     f"The salary on the bank statement is paid by someone other than the employer on the {where(other, 'en')}",
                     [(statement, "salary_transfer_company"), (other, key)], similarity=s)

    # ---- what the file still needs
    kind = form.get("applicant_type") or "employee"
    needed = [("id_front",), ("id_back",), BILLS, ("commercial_register",) if kind == "business" else ("hr_letter",)]
    have = {d["doc_type"] for d in uploaded}
    for group in needed:
        if not have & set(group):
            flags.append({"source": "document", "rule": "missing_document", "severity": "low", "status": "raised", "documents": [], "confirm": [],
                          "detail_ar": f"لم يُرفع مستند: {LABEL[group[0]][0]}", "detail_en": f"Not uploaded: {LABEL[group[0]][1]}", "evidence": {"doc_type": group[0]}})

    order = {"high": 0, "medium": 1, "low": 2}
    flags.sort(key=lambda f: (f["status"] != "raised", order[f["severity"]]))
    return flags


INCOMPLETE = ("missing_document", "type_needed")      # the file needs something from the officer; nothing was found wrong


def verdict(flags: list[dict]) -> tuple[str, str]:
    """(verdict, risk). Findings come first; then readings to confirm; then a file that is only incomplete."""
    findings = [f for f in flags if f["status"] == "raised" and f["rule"] not in INCOMPLETE]
    if findings:
        return "flagged_for_review", "high" if any(f["severity"] == "high" for f in findings) else "medium"
    if any(f["status"] == "needs_confirmation" for f in flags):
        return "confirm_readings", "medium"
    if flags:
        return "incomplete", "low"
    return "no_issues_found", "low"


def summarise(flags: list[dict], outcome: str) -> dict:
    """The reviewer's summary, written from the flags themselves. No model: nothing about a real applicant
    leaves this service, and the text cannot say more than the checks found."""
    findings = [f for f in flags if f["status"] == "raised" and f["rule"] not in INCOMPLETE]
    pending = [f for f in flags if f["status"] == "needs_confirmation"]
    missing = [f for f in flags if f["rule"] == "missing_document"]
    untyped = sum(f["rule"] == "type_needed" for f in flags)
    ar, en = [], []
    if outcome == "no_issues_found":
        return {"ar": "لم يُعثر على مؤشرات تستدعي المراجعة. القرار للموظف.", "en": "No indicators requiring review were found. The decision rests with the officer."}
    if findings:
        high = sum(f["severity"] == "high" for f in findings)
        ar.append(f"أُحيل الملف للمراجعة البشرية لوجود {len(findings)} مؤشر، منها {high} عالي الأهمية. أبرزها: " + "؛ ".join(f["detail_ar"] for f in findings[:2]) + ".")
        en.append(f"The file is referred for human review: {len(findings)} indicator(s), {high} of high severity. Main points: " + "; ".join(f["detail_en"] for f in findings[:2]) + ".")
    if pending:
        ar.append(f"{len(pending)} اختلاف يعتمد على قراءة غير مؤكدة: يؤكد الموظف القراءة أولاً.")
        en.append(f"{len(pending)} difference(s) rest on a reading the system was unsure of: the officer confirms the reading first.")
    if missing:
        ar.append("مستندات ناقصة: " + "، ".join(LABEL[f["evidence"]["doc_type"]][0] for f in missing) + ".")
        en.append("Missing documents: " + ", ".join(LABEL[f["evidence"]["doc_type"]][1] for f in missing) + ".")
    if untyped:
        ar.append(f"{untyped} مستند ينتظر تحديد نوعه.")
        en.append(f"{untyped} document(s) wait for their type to be chosen.")
    ar.append("هذه مؤشرات للمراجعة وليست حكماً؛ القرار للموظف.")
    en.append("These are indicators for review, not a judgement; the decision rests with the officer.")
    return {"ar": " ".join(ar), "en": " ".join(en)}
