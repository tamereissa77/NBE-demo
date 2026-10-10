"""D1 checks on an uploaded loan file, run on made-up readings: no model, database or image is needed.
    docker run --rm -v ./tests:/tests:ro nbe-d1 python /tests/d1_rules.py

Rules under test (services/d1_docverify/app/rules.py, nid.py):
- A consistent file raises nothing; an edited salary, a different name, a different ID number, an expired
  card, a letter with no stamp or signature each raise their own flag.
- The national ID number is checked against itself: its length, the birth date and gender it encodes.
- A mismatch that rests on a field the reader was unsure of asks the officer to confirm the reading first;
  once the officer confirms or corrects the field, the check gives a plain answer.
- Names: compound names and a shorter form of the same name match; a different first name does not; an
  Arabic name and a Latin one are left to the officer.
- The summary is written from the flags and never says "fraud".
- A second reading changes an unsure field only when one half of the page is confident of another value
  and no half repeats the first reading; the field stays marked unsure either way.
- The salary letter is checked against the salary rows of the bank statement, so a letter and a declared
  salary that agree with each other but not with the money that arrived are flagged; an invoice must add up;
  a letter dated in the future or long ago is flagged.
- A PDF's own record is read: the program that wrote it, a later modification, a second save (app/pdfdoc.py).
All people, numbers and companies below are invented.
"""
import asyncio
import io
import os
import sys
from datetime import date

from PIL import Image

os.environ.setdefault("DOCVLM_URL", "http://reader.invalid")
sys.path.insert(0, ".")        # the service's working directory (/srv in the image) holds `app`
from app import nid, pdfdoc, reader, rules

TODAY = date(2026, 10, 9)
NID = "29001011234571"         # 1990-01-01, governorate 12, male
results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(f"  {'PASS' if ok else 'FAIL'} {label}", flush=True)


def file(**changes) -> tuple[dict, list[dict]]:
    """A consistent employee file; `changes` overrides one field as 'doc.field' = value, or 'doc' = None to drop it."""
    form = {"applicant_name": "أحمد محمود عبد الرحمن السيد", "national_id": NID, "monthly_salary": 18500, "employer": "شركة النيل للصناعات الغذائية",
            "address": "12 شارع التحرير الدقي الجيزة", "loan_amount": 250000, "applicant_type": "employee"}
    docs = {
        "id_front": {"full_name": "أحمد محمود عبدالرحمن السيد", "national_id": NID, "birthdate_printed": "1990-01-01", "address": "12 ش التحرير - الدقي - الجيزة"},
        "id_back": {"national_id": NID, "expiry_date": "2029-05-14", "gender": "ذكر", "marital_status": "متزوج", "job_title": "محاسب"},
        "hr_letter": {"employee_name": "أحمد محمود عبد الرحمن", "national_id": NID, "company_name": "شركة النيل للصناعات الغذائية", "job_title": "محاسب أول",
                      "salary_amount": "18,500", "hire_date": "2016-03-01", "has_stamp": True, "has_signature": True},
        "electricity_bill": {"customer_name": "أحمد محمود عبدالرحمن", "address": "12 شارع التحرير الدقي الجيزة", "bill_date": "2026-08-20", "amount": "412.5",
                             "meter_number": "55120987", "has_stamp": False, "has_signature": False},
    }
    doubt: dict[str, list[str]] = {}
    for key, value in changes.items():
        doc, _, field = key.partition(".")
        if doc == "form":
            form[field] = value
        elif doc == "doubt":
            doubt.setdefault(field, []).append(value)
        elif not field:
            docs.pop(doc) if value is None else docs.__setitem__(doc, value)
        else:
            docs[doc][field] = value
    return form, [{"id": k, "doc_type": k, "values": v, "doubt": doubt.get(k, [])} for k, v in docs.items()]


def run(**changes) -> list[dict]:
    return rules.check(*file(**changes), TODAY)


def has(flags, rule, status="raised", severity=None) -> bool:
    return any(f["rule"] == rule and f["status"] == status and severity in (None, f["severity"]) for f in flags)


def main() -> None:
    print("A consistent file")
    flags = run()
    check(flags == [], "raises nothing")
    check(rules.verdict(flags) == ("no_issues_found", "low"), "verdict: no issues found, low risk")

    print("Tampered or mismatched values")
    flags = run(**{"hr_letter.salary_amount": "32,000"})
    check(has(flags, "salary_mismatch", severity="high"), "salary on the letter far from the declared salary is flagged high")
    check(rules.verdict(flags) == ("flagged_for_review", "high"), "verdict: flagged for review, high risk")
    check(not has(run(**{"hr_letter.salary_amount": "19,900"}), "salary_mismatch"), "a salary within 15% of the declared one is not flagged")
    check(has(run(**{"hr_letter.employee_name": "محمد عادل السيد حسن"}), "name_mismatch", severity="high"), "another person's name on the HR letter is flagged high")
    check(has(run(**{"electricity_bill.customer_name": "سعاد إبراهيم فوزي"}), "name_mismatch", severity="medium"), "another name on the bill is flagged medium")
    check(has(run(**{"hr_letter.company_name": "مجموعة الدلتا للمقاولات"}), "employer_mismatch"), "an employer other than the declared one is flagged")
    check(has(run(**{"electricity_bill.address": "45 طريق الحرية سموحة الإسكندرية"}), "address_mismatch", severity="medium"), "a bill for another address is flagged")
    check(has(run(**{"hr_letter.has_stamp": False}), "missing_stamp") and has(run(**{"hr_letter.has_signature": False}), "missing_signature"),
          "an HR letter with no stamp or no signature is flagged")
    check(not has(run(), "missing_stamp"), "a bill with no stamp is not flagged")

    print("The national ID number")
    check(nid.inspect(NID)[0] == {"national_id": NID, "birthdate": "1990-01-01", "gender": "ذكر"}, "a well-formed number gives its birth date and gender")
    check(nid.inspect("٢٩٠٠١٠١١٢٣٤٥٧١")[0] is not None, "Arabic-Indic digits are read as the same number")
    check(nid.inspect("28455895209976")[0] is None and nid.inspect("2900101123457")[0] is None, "month 55 or 13 digits cannot be a national ID")
    check(has(run(**{"id_front.national_id": "28455895209976"}), "id_number_invalid", severity="high"), "a number that cannot be a national ID is flagged")
    flags = run(**{"id_back.national_id": "29001011234591"})
    check(has(flags, "id_sides_mismatch") and flags[0]["evidence"].get("differing_digits") == 1, "front and back differing in one digit is flagged with the count")
    check(has(run(**{"hr_letter.national_id": "29001011234373"}), "nid_mismatch"), "an ID number on the HR letter that is not the card's is flagged")
    check(has(run(**{"form.national_id": "29505121401238"}), "nid_mismatch"), "a declared ID number that is not the card's is flagged")
    check(not has(run(**{"hr_letter.national_id": None}), "id_number_invalid"), "an HR letter that prints no ID number is not flagged for it")
    check(has(run(**{"id_front.birthdate_printed": "1990-02-01"}), "id_birthdate_mismatch"), "a printed birth date that disagrees with the number is flagged")
    check(has(run(**{"id_back.gender": "أنثى"}), "id_gender_mismatch"), "a printed gender that disagrees with the number is flagged")
    check(has(run(**{"id_back.expiry_date": "2025-12-31"}), "id_expired", severity="high"), "an expired card is flagged high")

    print("Readings the model was unsure of")
    changed = {"hr_letter.employee_name": "محمد عادل السيد حسن", "doubt.hr_letter": "employee_name"}
    flags = run(**changed)
    check(has(flags, "name_mismatch", status="needs_confirmation") and not has(flags, "name_mismatch"), "a mismatch on an unsure reading asks for confirmation, it is not raised")
    check(flags[0]["confirm"] == [{"document": "hr_letter", "field": "employee_name"}], "the flag names the field to confirm")
    check(rules.verdict(flags) == ("confirm_readings", "medium"), "verdict: confirm the readings first")
    form, docs = file(**changed)
    docs[2]["doubt"] = []                                              # the officer confirmed the reading as it is
    check(has(rules.check(form, docs, TODAY), "name_mismatch"), "once confirmed, the same mismatch is raised")
    docs[2]["values"]["employee_name"] = "أحمد محمود عبد الرحمن"        # or corrected it
    check(rules.check(form, docs, TODAY) == [], "once corrected to the real name, nothing is raised")

    print("Names")
    same = rules.name_similarity
    check(same("عبد الحميد حميدو عبدالحميد الجباوي", "عبدالحميد حميدو عبد الحميد الجباوى") == 1.0, "compound names and alef/ya spellings match")
    check(same("أحمد محمود عبدالرحمن السيد", "أحمد محمود عبد الرحمن") == 1.0, "a shorter form of the same name matches")
    check(same("عبدالحميد حميدو غبدالحميد الجباوي", "عبدالحميد حميدو عبدالحميد الجباوي") == 1.0, "one misread letter does not break a match")
    check(same("محمود أحمد عبدالرحمن", "أحمد محمود عبدالرحمن") < rules.NAME_MATCH, "a different first name is not the same person")
    check(same("أحمد", "أحمد محمود عبدالرحمن") < rules.NAME_MATCH, "one name part alone is not enough")
    check(same("Ahmed Mahmoud Abdelrahman", "أحمد محمود عبدالرحمن") is None, "an Arabic and a Latin name cannot be compared")
    flags = run(**{"hr_letter.employee_name": "Ahmed Mahmoud Abdelrahman"})
    check(has(flags, "name_not_comparable", status="needs_confirmation") and not has(flags, "name_mismatch"), "a Latin-script letter is left to the officer, not flagged as a mismatch")

    print("Dates and missing documents")
    check(has(run(**{"electricity_bill.bill_date": "2026-05-01"}), "bill_date", severity="low"), "a bill older than three months is flagged low")
    check(has(run(**{"electricity_bill.bill_date": "2026-12-01"}), "bill_date", severity="high"), "a bill dated in the future is flagged high")
    check(has(run(**{"hr_letter.hire_date": "2027-01-01"}), "hire_date_future"), "a hire date in the future is flagged")
    flags = run(hr_letter=None)
    check(has(flags, "missing_document") and rules.verdict(flags) == ("incomplete", "low"), "a file without an HR letter is incomplete, not flagged")
    form, docs = file(hr_letter=None)
    docs.append({"id": "x", "doc_type": "hr_letter", "values": {}, "doubt": [], "unread": True})
    check(rules.check(form, docs, TODAY) == [], "a document uploaded but not read yet counts as present and is not checked")
    form, docs = file(**{"form.applicant_type": "business"})
    check(any(f["evidence"].get("doc_type") == "commercial_register" for f in rules.check(form, docs, TODAY)), "a business applicant needs a commercial register")
    form, docs = file()
    docs[0] = {"id": "id_front", "doc_type": "id_front", "values": {}, "doubt": [], "error": "no JSON"}
    check(has(rules.check(form, docs, TODAY), "unreadable_document"), "a document the reader could not read is flagged")

    print("Summary")
    flags = run(**{"hr_letter.salary_amount": "32,000", "hr_letter.has_stamp": False})
    text = rules.summarise(flags, rules.verdict(flags)[0])
    check("احتيال" not in text["ar"] and "fraud" not in text["en"].lower() and "تزوير" not in text["ar"], "never says fraud or forgery")
    check("2" in text["ar"] and "القرار للموظف" in text["ar"] and "officer" in text["en"], "counts the indicators and leaves the decision to the officer")
    check("officer" in rules.summarise([], "no_issues_found")["en"], "a clean file still leaves the decision to the officer")

    print("Second reading of unsure fields")
    buf = io.BytesIO()
    Image.new("RGB", (60, 100), "white").save(buf, "PNG")
    first = {"fields": {"customer_name": "سعيد", "address": "شارع ١", "amount": "100", "has_stamp": False},
             "confidence": {"customer_name": 0.4, "address": 0.5, "amount": 0.99}, "doubt": ["customer_name", "address", "has_stamp"], "ms": 10}

    def again(*halves):
        answers = [{"fields": f, "confidence": c, "doubt": [], "ms": 5} for f, c in halves]

        async def fake(doc_type, content):
            return answers.pop(0)
        reader._adapter_read = fake
        return asyncio.run(reader.second_read("electricity_bill", buf.getvalue(), first))

    out = again(({"customer_name": "سعيد محمود", "address": None}, {"customer_name": 0.97}), ({"customer_name": None, "address": "شارع ٢"}, {"address": 0.6}))
    check(out["fields"]["customer_name"] == "سعيد محمود" and out["second_read"] == {"customer_name": "سعيد"}, "a half that is confident of another value replaces the unsure one")
    check(out["fields"]["address"] == "شارع ١" and "customer_name" in out["doubt"], "an unconfident half changes nothing, and the field stays marked unsure")
    check(out["ms"] == 20 and out["fields"]["amount"] == "100" and out["fields"]["has_stamp"] is False, "sure fields and yes/no fields are left alone; the time is added")
    out = again(({"customer_name": "سعيد", "address": None}, {"customer_name": 0.99}), ({"customer_name": "سعد علي", "address": None}, {"customer_name": 0.99}))
    check(out["fields"]["customer_name"] == "سعيد", "a half that repeats the first reading keeps it")
    out = again(({"customer_name": "سعد علي"}, {"customer_name": 0.95}), ({"customer_name": "سيد حسن"}, {"customer_name": 0.95}))
    check(out["fields"]["customer_name"] == "سعيد", "two confident halves that disagree change nothing")
    check(asyncio.run(reader.second_read("id_front", buf.getvalue(), first)) is first, "ID cards are not read a second time here")

    print("Salary letter against the bank statement, letter date, invoice")
    paid = {"account_holder": "أحمد محمود عبد الرحمن", "salary_transfer_amount_1": 18500, "salary_transfer_amount_2": "18,500.00", "salary_transfer_amount_3": 18500.0,
            "salary_transfer_company": "شركة النيل للصناعات الغذائية", "statement_to_date": "2026-09-30"}
    check(run(bank_statement=paid) == [], "a statement that shows the letter's salary, paid by the letter's employer, raises nothing")
    flags = run(bank_statement=paid, **{"hr_letter.salary_amount": "32,000", "form.monthly_salary": 32000})
    check(has(flags, "salary_vs_statement", severity="high") and not has(flags, "salary_mismatch"),
          "a letter and a declared salary that agree with each other but not with the statement are flagged")
    check(has(run(bank_statement={**paid, "salary_transfer_amount_2": 37000}), "salary_vs_statement"), "one salary row that is double the letter is flagged")
    check(has(run(hr_letter=None, bank_statement={**paid, "salary_transfer_amount_2": 37000}), "salary_credits_vary", severity="medium"),
          "without a letter, salary rows that differ from one another are still flagged")
    check(has(run(bank_statement={**paid, "salary_transfer_company": "مجموعة الدلتا للمقاولات"}), "payer_mismatch", severity="high"), "a salary paid by another company than the letter's is flagged")
    check(has(run(bank_statement={**paid, "account_holder": "محمد عادل السيد حسن"}), "name_mismatch", severity="high"), "a statement in another person's name is flagged")
    check(has(run(bank_statement={**paid, "statement_to_date": "2026-03-31"}), "statement_date", severity="low"), "a statement that ends more than three months ago is flagged low")
    check(has(run(**{"hr_letter.letter_date": "2026-12-20"}), "letter_date", severity="high"), "a letter dated in the future is flagged high")
    check(has(run(**{"hr_letter.letter_date": "2026-05-01"}), "letter_date", severity="low") and not has(run(**{"hr_letter.letter_date": "2026-09-20"}), "letter_date"),
          "a letter older than 90 days is flagged low, a recent one is not")
    check(has(run(invoice={"subtotal_amount": 59594, "vat_amount": 8343, "total_amount": 203811}), "invoice_arithmetic", severity="high")
          and not has(run(invoice={"subtotal_amount": "59,594", "vat_amount": 8343, "total_amount": 67937.0}), "invoice_arithmetic"),
          "an invoice whose total is not subtotal plus VAT is flagged; one that adds up is not")
    check(has(run(id_front=None, **{"electricity_bill.address": "45 طريق الحرية سموحة الإسكندرية"}), "address_mismatch"),
          "without the ID card, a bill for another address than the declared one is still flagged")

    print("PDF record")
    page = io.BytesIO()
    Image.new("RGB", (300, 420), "white").save(page, "PDF", producer="Scanner PDF writer", creator="Scanner")
    clean = page.getvalue()
    info = pdfdoc.inspect(clean)
    check(pdfdoc.is_pdf(clean) and not pdfdoc.is_pdf(buf.getvalue()) and info["findings"] == [] and info["revisions"] == 1, "a PDF written once by a scanner raises nothing")
    png, pages = pdfdoc.render(clean)
    check(pages == 1 and Image.open(io.BytesIO(png)).format == "PNG" and max(Image.open(io.BytesIO(png)).size) >= 1900, "its first page is rendered to an image for the reader")
    import time as _time
    page = io.BytesIO()
    Image.new("RGB", (300, 420), "white").save(page, "PDF", producer="Adobe Photoshop 25.1 (Windows)", creator="Adobe Photoshop 25.1 (Windows)",
                                               creationDate=_time.strptime("2026-09-14 10:12", "%Y-%m-%d %H:%M"), modDate=_time.strptime("2026-09-16 09:00", "%Y-%m-%d %H:%M"))
    info = pdfdoc.inspect(page.getvalue() + b"\n%%EOF\n")
    check(info["findings"] == ["pdf_editor", "pdf_modified", "pdf_revisions"] and info["editor"] == "photoshop" and info["revisions"] == 2,
          "an image editor's name, a later modification and a second save are each reported")

    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
