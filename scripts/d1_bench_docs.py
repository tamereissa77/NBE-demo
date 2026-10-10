# -*- coding: utf-8 -*-
"""Benchmark files for D1's upload flow: 9 invented applicants, 27 documents, 10 planted forgeries, one planted
false positive and a ground-truth manifest. tests/d1_bench.py pushes them through the service and scores it.

The pages are drawn in the layouts the document reader was trained on, by the fine-tune project's own
generators (HR letter, bills, commercial register), plus a bank statement and an invoice drawn here. Each
page is first made to look photographed (camera noise, a first JPEG save); a forgery is then made the way
a real one is, on that picture: a value typed over it, a stamp copied, a file re-saved by an editor. So the
traces the image checks look for are there, and so are the contradictions the rules look for.

Every person, number and company is invented, and every page carries a "test sample" line.

    python scripts/d1_bench_docs.py <fine-tune repo> [out dir]        (Windows: uses the system's Arabic fonts)
"""
from __future__ import annotations

import io
import json
import math
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO = Path(sys.argv[1])
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parents[1] / "data" / "generated" / "d1_bench"
sys.path.insert(0, str(REPO))
from nbe_finetune import generate_commercial_registers as cr  # noqa: E402
from nbe_finetune import generate_documents as gd  # noqa: E402
from nbe_finetune import generate_hr_letters as hr  # noqa: E402

FONT, BOLD = "C:/Windows/Fonts/tahoma.ttf", "C:/Windows/Fonts/tahomabd.ttf"
MARK = "عينة اختبار - ليست مستنداً رسمياً"
INK, DARK = (28, 40, 130), (20, 20, 20)
SEED = 2026
NOISE = np.random.default_rng(SEED)
_PERSON = cr._person


class Sheet:
    """A page drawn here (bank statement, invoice): shaped Arabic text, right-aligned like the real ones."""

    def __init__(self, w: int, h: int):
        self.image = Image.new("RGB", (w, h), (255, 255, 255))
        self.d = ImageDraw.Draw(self.image)
        self.w, self.h = w, h

    def text(self, value, x, y, size=17, bold=False, fill=DARK, anchor="ra"):
        font = ImageFont.truetype(BOLD if bold else FONT, size)
        shown = gd.get_display(gd.arabic_reshaper.reshape(str(value)))
        self.d.text((x, y), shown, font=font, fill=fill, anchor=anchor)
        return [int(v) for v in self.d.textbbox((x, y), shown, font=font, anchor=anchor)]


def stamp(image: Image.Image, cx: int, cy: int, lines: list[str], tilt: float = -11) -> Image.Image:
    """A round ink stamp, drawn large and shrunk so the strokes are smooth."""
    s, size = 4, 190
    layer = Image.new("RGBA", (size * s, size * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c, r = size // 2 * s, 84 * s
    d.ellipse([c - r, c - r, c + r, c + r], outline=(36, 62, 165, 210), width=4 * s)
    d.ellipse([c - r + 13 * s, c - r + 13 * s, c + r - 13 * s, c + r - 13 * s], outline=(36, 62, 165, 210), width=int(1.5 * s))
    for text, y, pt in zip(lines, (64, 94, 121), (18, 16, 13)):
        d.text((c, y * s), gd.get_display(gd.arabic_reshaper.reshape(text)), font=ImageFont.truetype(BOLD, pt * s), fill=(36, 62, 165, 215), anchor="ma")
    layer = layer.rotate(tilt, resample=Image.BICUBIC).resize((size, size), Image.LANCZOS)
    out = image.convert("RGBA")
    out.alpha_composite(layer, (cx - size // 2, cy - size // 2))
    return out.convert("RGB")


def signature(image: Image.Image, x0: int, base: int) -> Image.Image:
    s = 4
    layer = Image.new("RGBA", (image.width * s, image.height * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    def stroke(points, width):
        d.line([(x * s, y * s) for x, y in points], fill=INK + (235,), width=int(width * s), joint="curve")

    stroke([(x0 + 26 * math.sin(t * 2.2) * (1 - t) + 14 * t, base - 46 * math.sin(math.pi * t) + 8 * t) for t in (i / 60 for i in range(61))], 2.2)
    stroke([(x0 + 18 + 138 * t + 7 * math.sin(t * 34), base - 4 + (17 * (1 - t) ** 1.5 + 3) * math.sin(t * 30 + 0.6) - 9 * math.sin(math.pi * t))
            for t in (i / 220 for i in range(221))], 1.9)
    stroke([(x0 + 6 + 170 * t, base + 17 - 9 * math.sin(math.pi * t) + 3 * t) for t in (i / 50 for i in range(51))], 1.6)
    out = image.convert("RGBA")
    out.alpha_composite(layer.resize(image.size, Image.LANCZOS))
    return out.convert("RGB")


# ---- the pages. Each returns (clean image, boxes of the values a forger would change)

def hr_letter(v: dict):
    page = hr.Letter(random.Random(1))
    page._regular, page._bold = FONT, BOLD
    page.centred(v["employer"], 92, page.font(27, True), (24, 30, 120))
    page.centred("إدارة الموارد البشرية", 142, page.font(15), (110, 110, 125))
    page.draw.line([(60, 182), (page.width - 60, 182)], fill=(45, 45, 60), width=2)
    b_date = page.text(f"القاهرة في: {v['letter_date']}", (52, 226), page.font(14), (80, 80, 95))
    title = page.centred("شهادة راتب", 286, page.font(22, True))
    page.draw.line([(title[0], title[3] + 3), (title[2], title[3] + 3)], fill=DARK, width=2)
    right = page.width - 64
    line1 = f"تشهد {v['employer']} بأن السيد/ {v['name']} والذي يحمل رقم قومي"
    line2 = f"{v['nid']} يعمل لدينا منذ تاريخ {hr._ltr(v['hired'])} بوظيفة {v['job']}."
    size = next(s for s in range(16, 10, -1) if max(page.draw.textlength(page._shape(t), font=page.font(s, True)) for t in (line1, line2)) <= right - 64)
    page.text(line1, (right, 349), page.font(size, True), (25, 45, 120), anchor="ra")
    page.text(line2, (right, 391), page.font(size, True), (25, 45, 120), anchor="ra")
    b_salary = page.text(f"وأن صافي راتبه الشهري هو ( {v['salary']:,} جنيه مصري ).", (right, 449), page.font(size, True), (25, 45, 120), anchor="ra")
    page.text("أعطيت هذه الشهادة بناءً على طلبه دون أدنى مسؤولية على الشركة.", (right, 515), page.font(size), (35, 35, 50), anchor="ra")
    page.draw.line([(90, 920), (270, 920)], fill=(60, 60, 80), width=1)
    page.text("مدير الموارد البشرية", (106, 926), page.font(13, True), (40, 40, 60))
    page.centred(MARK, page.height - 44, page.font(13), (150, 60, 60))
    image = stamp(signature(page.image, 98, 894), 300, 866, [v["employer"].replace("شركة ", ""), "الموارد البشرية", "القاهرة"])
    return image, {"salary": b_salary, "date": b_date}


def bill(kind: str, v: dict):
    gd._pick = lambda rng, items: v["name"] if items is gd.NAMES else v["address"] if items is gd.ADDRS else rng.choice(items)
    gd._date = lambda rng, y1, y2: v["bill_date"]
    page = (gd.gen_electricity_bill if kind == "electricity_bill" else gd.gen_utility_bill)(random.Random(v["seed"]))
    page.text(MARK, (page.width // 2 - 120, page.height - 40), page.font(14), (150, 60, 60))
    f = page.fields
    return page.image, {"name": f["subscriber_name"]["bbox_2d"], "address": (f.get("meter_address") or f["address"])["bbox_2d"]}


def register(v: dict):
    people = iter([v["owner"]])
    cr._person = lambda r: next(people, None) or _PERSON(r)
    cr._address = lambda r, city: v["address"]
    cr.OFFICES = [("مكتب سجل تجاري القاهرة", "القاهرة")]
    form = cr.render_landscape(random.Random(v["seed"]))
    form.draw = ImageDraw.Draw(form.image)
    form.text(MARK, (form.width // 2, form.height - 34), form.font(12, True), (150, 30, 30), anchor="ma")
    return form.image, {"owner": form.fields["owner_name"]["bbox_2d"], "stamp": [36, 540, 258, 682]}


def statement(v: dict):
    s = Sheet(900, 1200)
    s.text("بنك الواحة التجاري", 450, 44, 30, True, (120, 20, 40), "ma")
    s.text("كشف حساب", 450, 96, 22, True, anchor="ma")
    s.d.line([(50, 140), (850, 140)], fill=(120, 20, 40), width=2)
    y = 165
    for label, value in (("اسم العميل", v["name"]), ("رقم الحساب", v["account"]), ("الفترة من", v["from"]), ("إلى", v["to"])):
        s.text(f"{label} :", 850, y, 18, True)
        s.text(value, 690, y, 18)
        y += 38
    cols = {"date": 850, "what": 700, "debit": 380, "credit": 260, "balance": 140}
    y += 18
    for key, head in (("date", "التاريخ"), ("what", "وصف الحركة"), ("debit", "مدين"), ("credit", "دائن"), ("balance", "الرصيد")):
        s.text(head, cols[key], y, 16, True)
    s.d.line([(50, y + 30), (850, y + 30)], fill=(90, 90, 100), width=1)
    y += 44
    balance, credits = v["opening"], []
    for month, salary in zip(v["months"], v["credits"]):
        for day, what, amount in ((27, f"تحويل راتب - {v['payer']}", salary), (28, "سحب نقدي من الصراف الآلي", -v["withdraw"]), (29, "مشتريات بالبطاقة", -v["spend"])):
            balance += amount
            s.text(f"{month}/{day:02d}", cols["date"], y, 15)
            s.text(what, cols["what"], y, 15)
            box = s.text(f"{abs(amount):,.2f}", cols["credit" if amount > 0 else "debit"], y, 15)
            if amount > 0:
                credits.append(box)
            s.text(f"{balance:,.2f}", cols["balance"], y, 15)
            y += 40
    s.d.line([(50, y + 4), (850, y + 4)], fill=(90, 90, 100), width=1)
    s.text("الرصيد الختامي :", 850, y + 22, 18, True)
    s.text(f"{balance:,.2f}", 690, y + 22, 18, True)
    s.text(MARK, 450, s.h - 46, 13, fill=(150, 60, 60), anchor="ma")
    return stamp(s.image, 190, y + 150, ["بنك الواحة التجاري", "خدمة العملاء", "القاهرة"], tilt=8), {"credits": credits}


def invoice(v: dict):
    s = Sheet(820, 1100)
    s.text("شركة الريادة للتوريدات", 410, 46, 28, True, (20, 90, 90), "ma")
    s.text("فاتورة ضريبية", 410, 100, 22, True, anchor="ma")
    s.text("رقم التسجيل الضريبي : 412-558-906", 410, 140, 14, fill=(90, 90, 100), anchor="ma")
    s.d.line([(50, 176), (770, 176)], fill=(20, 90, 90), width=2)
    y = 200
    for label, value in (("العميل", v["customer"]), ("رقم الفاتورة", v["number"]), ("التاريخ", v["invoice_date"])):
        s.text(f"{label} :", 770, y, 18, True)
        s.text(value, 610, y, 18)
        y += 38
    y += 16
    cols = {"what": 770, "qty": 430, "price": 300, "value": 150}
    for key, head in (("what", "البيان"), ("qty", "الكمية"), ("price", "السعر"), ("value", "القيمة")):
        s.text(head, cols[key], y, 16, True)
    s.d.line([(50, y + 30), (770, y + 30)], fill=(90, 90, 100), width=1)
    y += 44
    for what, qty, price in v["items"]:
        s.text(what, cols["what"], y, 16)
        s.text(qty, cols["qty"], y, 16)
        s.text(f"{price:,}", cols["price"], y, 16)
        s.text(f"{qty * price:,}", cols["value"], y, 16)
        y += 40
    subtotal = sum(q * p for _, q, p in v["items"])
    vat = round(subtotal * 0.14)
    s.d.line([(50, y + 4), (770, y + 4)], fill=(90, 90, 100), width=1)
    y += 22
    s.text("المجموع قبل الضريبة :", 770, y, 17)
    s.text(f"{subtotal:,}", cols["value"], y, 17)
    s.text("ضريبة القيمة المضافة 14% :", 770, y + 40, 17)
    s.text(f"{vat:,}", cols["value"], y + 40, 17)
    s.text("الإجمالي (جنيه) :", 770, y + 90, 19, True)
    b_total = s.text(f"{v.get('total', subtotal + vat):,}", cols["value"], y + 90, 19, True)
    s.text(MARK, 410, s.h - 46, 13, fill=(150, 60, 60), anchor="ma")
    return stamp(s.image, 180, y + 220, ["الريادة للتوريدات", "الحسابات", "القاهرة"], tilt=-6), {"total": b_total}


# ---- photographed, then forged

def photographed(image: Image.Image, rng: random.Random) -> Image.Image:
    """Camera noise, a little softness and the camera's own JPEG save."""
    a = np.asarray(image.convert("RGB"), np.float32) + NOISE.normal(0, rng.uniform(3.2, 4.4), (image.height, image.width, 3))
    out = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.4))
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=rng.randint(76, 84))
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def typed_over(photo: Image.Image, forged: Image.Image, boxes: list, pad: int = 6) -> Image.Image:
    """The forged value as it looks on the clean page, pasted over the photograph: typed text on a patch with no camera noise."""
    x0, y0 = min(b[0] for b in boxes) - pad, min(b[1] for b in boxes) - pad
    x1, y1 = max(b[2] for b in boxes) + pad, max(b[3] for b in boxes) + pad
    out = photo.copy()
    out.paste(forged.crop((x0, y0, x1, y1)), (x0, y0))
    return out


def copied(photo: Image.Image, box: list, shift: tuple[int, int]) -> Image.Image:
    out = photo.copy()
    out.paste(photo.crop(tuple(box)), (box[0] + shift[0], box[1] + shift[1]))
    return out


def save_jpg(image: Image.Image, path: Path, software: str | None = None) -> None:
    exif = Image.Exif()
    exif[0x0110] = "SM-A546E"
    if software:
        exif[0x0131] = software
    image.save(path, "JPEG", quality=92, exif=exif.tobytes())


def save_pdf(image: Image.Image, path: Path, edited: bool) -> None:
    """A scan saved as a PDF. Edited: an image editor wrote it, two days after the scan, and saved it on top of the first version."""
    made = datetime(2026, 9, 14, 10, 12, 5)
    image.save(path, "PDF", resolution=150, creator="Scanner" if not edited else "Adobe Photoshop 25.1 (Windows)",
               producer="Scanner PDF writer" if not edited else "Adobe Photoshop 25.1 (Windows)",
               creationDate=made.timetuple(), modDate=(made + timedelta(days=2 if edited else 0)).timetuple())
    if edited:
        try:
            from pypdf import PdfReader, PdfWriter
            writer = PdfWriter(clone_from=PdfReader(path), incremental=True)
            writer.add_metadata({"/Subject": "updated"})
            with open(path, "wb") as f:
                writer.write(f)
        except Exception:  # noqa: BLE001 - without pypdf: the end marker of a second save, which is what D1 counts
            with open(path, "ab") as f:
                f.write(b"\n%%EOF\n")


def national_id(rng: random.Random, year: int, male: bool) -> str:
    """A well-formed number for an invented person: century, birth date, governorate, serial with the gender digit."""
    serial = rng.randint(100, 999) * 10 + (rng.choice([1, 3, 5, 7, 9]) if male else rng.choice([2, 4, 6, 8]))
    return f"{'2' if year < 2000 else '3'}{year % 100:02d}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}{rng.choice(['01', '02', '12', '21']):s}{serial:04d}{rng.randint(1, 9)}"


PEOPLE = [("أحمد محمود عبد الرحمن السيد", "17 شارع التحرير - الدقي - الجيزة"), ("منى سامي حسن الشريف", "42 شارع مصطفى النحاس - مدينة نصر - القاهرة"),
          ("يوسف خالد إبراهيم النجار", "8 طريق الحرية - سموحة - الإسكندرية"), ("سارة إبراهيم فوزي عثمان", "25 شارع الجمهورية - المنصورة - الدقهلية"),
          ("عمر طارق حسنين مراد", "61 شارع 9 - المعادي - القاهرة"), ("ليلى مصطفى عزت راغب", "33 شارع الهرم - الجيزة"),
          ("كريم وائل منصور بدوي", "14 شارع فؤاد - محطة الرمل - الإسكندرية"), ("هدى أشرف رضوان سليم", "70 شارع النصر - المعادي الجديدة - القاهرة"),
          ("طارق حسن عبد العزيز نصار", "5 شارع البحر - طنطا - الغربية")]
EMPLOYERS = ["شركة الأفق للبرمجيات", "مجموعة الدلتا للمقاولات", "شركة الواحة للتجارة", "مصنع السلام للنسيج", "شركة البحر للسياحة"]
JOBS = ["محاسب أول", "مهندسة مدنية", "مطور برمجيات", "مديرة جودة", "مشرف مبيعات"]
ITEMS = [("خامات تعبئة", 20, 450), ("معدات تشغيل", 2, 8600), ("نقل وتوريد", 1, 900)]


def build() -> dict:
    rng = random.Random(SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    for old in list(OUT.glob("*.jpg")) + list(OUT.glob("*.pdf")):
        old.unlink()
    manifest = {"seed": SEED, "note": "Invented people and companies; every page carries a test-sample line.", "packs": []}

    def add(pack, kind, image, forged=None, software=None, false_positive=None, pdf=None, printed=None):
        """`printed`: what the page shows for the fields the reader's base model is asked for, to score its reading."""
        name = f"{pack['id']}_{kind}.{'pdf' if pdf is not None else 'jpg'}"
        save_pdf(image, OUT / name, pdf) if pdf is not None else save_jpg(image, OUT / name, software)
        doc = {"file": name, "doc_type": kind, "forged": bool(forged), "manipulation": forged, "printed": printed or {}}
        if false_positive:
            doc["planned_false_positive"] = false_positive
        pack["documents"].append(doc)

    # ---- five employees: HR letter, bank statement, a bill
    plans = {0: {"hr_letter": "salary_typed_over"}, 1: {"bank_statement": "salary_credit_typed_over", "electricity_bill": "name_typed_over"},
             2: {"hr_letter": "employer_not_the_payer"}, 3: {"hr_letter": "letter_date_typed_over"}, 4: {}}
    for i in range(5):
        name, address = PEOPLE[i]
        salary = rng.choice([14500, 18500, 22000, 27500, 31000])
        v = {"name": name, "address": address, "nid": national_id(rng, rng.randint(1978, 1996), i % 2 == 0), "employer": EMPLOYERS[i], "job": JOBS[i],
             "salary": salary, "hired": f"{rng.randint(1, 28):02d}-{rng.randint(1, 12):02d}-{rng.randint(2012, 2022)}", "letter_date": "2026/09/20",
             "bill_date": "2026/09/05", "seed": 100 + i, "account": f"{rng.randint(10 ** 13, 10 ** 14 - 1)}", "from": "2026/07/01", "to": "2026/09/30",
             "months": ["2026/07", "2026/08", "2026/09"], "credits": [salary] * 3, "payer": EMPLOYERS[i], "opening": rng.randint(4000, 30000),
             "withdraw": rng.choice([3000, 5000, 8000]), "spend": rng.randint(900, 4200)}
        plan = plans[i]
        letter = dict(v)
        if plan.get("hr_letter") == "employer_not_the_payer":            # a letter from a company that never paid this person
            letter["employer"] = "شركة الصفوة للاستثمار"
        declared_salary = salary + (12000 if plan.get("hr_letter") == "salary_typed_over" else 0)   # the applicant declares what the letter says
        pack = {"id": f"E{i + 1}", "form": {"applicant_name": name, "national_id": v["nid"], "monthly_salary": declared_salary,
                                             "employer": letter["employer"], "address": address, "applicant_type": "employee"}, "documents": []}
        clean, boxes = hr_letter(letter)
        photo = photographed(clean, rng)
        if plan.get("hr_letter") == "salary_typed_over":
            forged, fb = hr_letter({**letter, "salary": declared_salary})
            photo = typed_over(photo, forged, [boxes["salary"], fb["salary"]])
        elif plan.get("hr_letter") == "letter_date_typed_over":
            forged, fb = hr_letter({**letter, "letter_date": "2026/12/20"})
            photo = typed_over(photo, forged, [boxes["date"], fb["date"]])
        add(pack, "hr_letter", photo, plan.get("hr_letter"),
            printed={"salary_amount": declared_salary, "letter_date": "2026-12-20" if plan.get("hr_letter") == "letter_date_typed_over" else "2026-09-20"})

        clean, boxes = statement(v)
        photo = photographed(clean, rng)
        shown = [salary] * 3
        if plan.get("bank_statement"):
            shown = [salary, salary * 2, salary]
            forged, fb = statement({**v, "credits": shown})
            photo = typed_over(photo, forged, [boxes["credits"][1], fb["credits"][1]])
        add(pack, "bank_statement", photo, plan.get("bank_statement"), printed={"salary_credits": shown, "salary_payer_name": v["payer"]})

        kind = "electricity_bill" if i % 2 else "utility_bill"
        kind = "electricity_bill" if "electricity_bill" in plan else kind
        clean, boxes = bill(kind, v)
        photo = photographed(clean, rng)
        if plan.get(kind) == "name_typed_over":
            forged, fb = bill(kind, {**v, "name": "محمد عادل السيد حسين"})
            photo = typed_over(photo, forged, [boxes["name"], fb["name"]])
        fp = "genuine page, shared through a scanning app that left its name in the file" if i == 4 else None
        add(pack, kind, photo, plan.get(kind), software="Microsoft Lens" if fp else None, false_positive=fp)
        manifest["packs"].append(pack)

    # ---- four business owners: commercial register, invoice, a bill
    plans = {0: {"commercial_register": "stamp_copied"}, 1: {"invoice": "total_typed_over_in_editor"},
             2: {"commercial_register": "owner_typed_over", "utility_bill": "address_typed_over"}, 3: {"invoice": "pdf_edited_and_saved_again"}}
    for i in range(4):
        name, address = PEOPLE[5 + i]
        v = {"owner": name, "name": name, "address": address, "seed": 200 + i, "bill_date": "2026/09/08", "customer": name,
             "number": f"INV-{rng.randint(10000, 99999)}", "invoice_date": "2026/09/12",
             "items": [(what, qty + rng.randint(0, 6), price + rng.randint(0, 300)) for what, qty, price in ITEMS]}
        plan = plans[i]
        pack = {"id": f"B{i + 1}", "form": {"applicant_name": name, "national_id": national_id(rng, rng.randint(1970, 1990), i % 2 == 0),
                                             "monthly_salary": None, "employer": "", "address": address, "applicant_type": "business"}, "documents": []}
        clean, boxes = register(v)
        photo = photographed(clean, rng)
        if plan.get("commercial_register") == "stamp_copied":
            photo = copied(photo, boxes["stamp"], (430, -150))
        elif plan.get("commercial_register") == "owner_typed_over":
            forged, fb = register({**v, "owner": "محمود سعيد عبد الله خليل"})
            photo = typed_over(photo, forged, [boxes["owner"], fb["owner"]])
        add(pack, "commercial_register", photo, plan.get("commercial_register"))

        clean, boxes = invoice(v)
        photo = photographed(clean, rng)
        software = None
        subtotal = sum(q * p for _, q, p in v["items"])
        total = subtotal + round(subtotal * 0.14)
        if plan.get("invoice") == "total_typed_over_in_editor":
            total *= 3
            forged, fb = invoice({**v, "total": total})
            photo, software = typed_over(photo, forged, [boxes["total"], fb["total"]]), "Adobe Photoshop 25.1 (Windows)"
        add(pack, "invoice", photo, plan.get("invoice"), software=software, pdf=(plan.get("invoice") == "pdf_edited_and_saved_again") if i == 3 else None,
            printed={"subtotal_amount": subtotal, "vat_amount": round(subtotal * 0.14), "total_amount": total})

        kind = "utility_bill" if i % 2 == 0 else "electricity_bill"
        clean, boxes = bill(kind, v)
        photo = photographed(clean, rng)
        if plan.get(kind) == "address_typed_over":
            forged, fb = bill(kind, {**v, "address": "90 شارع الثورة - مصر الجديدة - القاهرة"})
            photo = typed_over(photo, forged, [boxes["address"], fb["address"]])
        add(pack, kind, photo, plan.get(kind))
        manifest["packs"].append(pack)

    docs = [d for p in manifest["packs"] for d in p["documents"]]
    manifest.update(document_count=len(docs), forged_count=sum(d["forged"] for d in docs),
                    false_positive=next(d["file"] for d in docs if d.get("planned_false_positive")))
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    m = build()
    print(f"D1 benchmark: {m['document_count']} documents in {len(m['packs'])} files, {m['forged_count']} forged, false positive: {m['false_positive']} -> {OUT}")
