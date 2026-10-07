"""D1 synthetic loan packs (PLAN.md §4 D1): 8 applicants, 40 documents, 10 deliberate forgeries,
1 planned false positive, and a ground-truth manifest.

Safety: every document is a fictitious, non-official layout with a SPECIMEN watermark. No real
person, ID number, company, bank or government design is reproduced, so nothing here can serve
as a usable fake document.

Forgeries are made the way a real tamperer would: the genuine document is saved, then a region is
re-rendered with a changed value and pasted back (or copied within the page), and the file is
re-saved. That leaves the traces the D1 forensics look for: error-level differences, copy-move
duplicates, metadata edits, and cross-document inconsistencies.
"""
import io
import json
import random
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path("/repo/data/generated/d1")
FONT_DIR = Path("/usr/share/fonts/truetype/noto")
W, H = 1240, 1754                       # A4 at 150 dpi
INK = (25, 25, 35)
SEED = 2026


def font(size: int, kind: str = "naskh", bold: bool = False) -> ImageFont.FreeTypeFont:
    """Arabic body text uses Amiri: unlike Noto Naskh it also has Latin letters, digits and punctuation
    (/, -, parentheses), so mixed lines such as dates and masked IDs render without missing glyphs."""
    if kind == "naskh":
        path = f"/usr/share/fonts/opentype/fonts-hosny-amiri/Amiri-{'Bold' if bold else 'Regular'}.ttf"
    else:
        name = {"kufi": "NotoKufiArabic", "sans": "NotoSans"}[kind]
        path = str(FONT_DIR / f"{name}-{'Bold' if bold else 'Regular'}.ttf")
    return ImageFont.truetype(path, size)


def ar(d: ImageDraw.ImageDraw, x: int, y: int, text: str, size: int = 30, bold: bool = False, kind: str = "naskh",
       fill=INK) -> tuple[int, int, int, int]:
    """Right-aligned Arabic text whose right edge is at x. Returns the bounding box."""
    f = font(size, kind, bold)
    d.text((x, y), text, font=f, fill=fill, anchor="ra", direction="rtl", language="ar")
    return d.textbbox((x, y), text, font=f, anchor="ra", direction="rtl", language="ar")


def en(d: ImageDraw.ImageDraw, x: int, y: int, text: str, size: int = 24, bold: bool = False, fill=INK, anchor="la"):
    f = font(size, "sans", bold)
    d.text((x, y), text, font=f, fill=fill, anchor=anchor)
    return d.textbbox((x, y), text, font=f, anchor=anchor)


def specimen(img: Image.Image) -> None:
    """Diagonal SPECIMEN watermark: this is demo data, not a document."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for i, y in enumerate(range(150, img.height, 420)):
        x = 80 + (i % 2) * 260
        d.text((x, y), "SPECIMEN · عينة تجريبية", font=font(54, "naskh", True), fill=(200, 30, 30, 48),
               direction="ltr", language="ar")
    layer = layer.rotate(25, center=(img.width // 2, img.height // 2))
    img.paste(layer, (0, 0), layer)


def stamp(img: Image.Image, cx: int, cy: int, text: str, color=(30, 60, 150)) -> tuple[int, int, int, int]:
    d = ImageDraw.Draw(img)
    r = 95
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color, width=6)
    d.ellipse((cx - r + 14, cy - r + 14, cx + r - 14, cy + r - 14), outline=color, width=2)
    d.text((cx, cy - 18), text, font=font(26, "naskh", True), fill=color, anchor="mm", direction="rtl", language="ar")
    d.text((cx, cy + 22), "عينة", font=font(22, "naskh"), fill=color, anchor="mm", direction="rtl", language="ar")
    return (cx - r, cy - r, cx + r, cy + r)


def signature(d: ImageDraw.ImageDraw, x: int, y: int, rng: random.Random) -> None:
    pts = [(x + i * 14, y + int(18 * rng.uniform(-1, 1))) for i in range(14)]
    d.line(pts, fill=(20, 30, 90), width=3, joint="curve")


def avatar(img: Image.Image, box: tuple[int, int, int, int], rng: random.Random) -> None:
    """A drawn silhouette, never a real face."""
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    bg = tuple(rng.randint(180, 230) for _ in range(3))
    d.rectangle(box, fill=bg, outline=(90, 90, 90), width=2)
    cx, w, h = (x0 + x1) // 2, x1 - x0, y1 - y0
    tone = tuple(rng.randint(70, 140) for _ in range(3))
    d.ellipse((cx - w * 0.22, y0 + h * 0.15, cx + w * 0.22, y0 + h * 0.52), fill=tone)
    d.pieslice((x0 + w * 0.12, y0 + h * 0.55, x1 - w * 0.12, y1 + h * 0.45), 180, 360, fill=tone)


def header(img: Image.Image, title_ar: str, org_ar: str, org_en: str, color=(0, 90, 70)) -> ImageDraw.ImageDraw:
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 150), fill=color)
    ar(d, W - 60, 28, org_ar, 40, True, fill="white")
    en(d, 60, 48, org_en, 26, True, fill="white")
    ar(d, W - 60, 190, title_ar, 44, True)
    d.line((60, 270, W - 60, 270), fill=color, width=3)
    return d


def scan_look(img: Image.Image, rng: random.Random, heavy: bool = False) -> Image.Image:
    """Slight rotation, blur and noise so pages look scanned; heavy=True for the planned false positive."""
    angle = rng.uniform(-0.6, 0.6) * (3 if heavy else 1)
    img = img.rotate(angle, expand=False, fillcolor="white", resample=Image.BICUBIC)
    if heavy:
        img = img.filter(ImageFilter.GaussianBlur(1.1))
    # Sensor noise of a real scan (about 3 grey levels per pixel, more for the phone re-scan)
    arr = np.asarray(img, dtype=np.float32)
    arr += np.random.default_rng(rng.randint(0, 2**31)).normal(0, 6.0 if heavy else 3.2, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def save_jpeg(img: Image.Image, path: Path, quality: int = 92, software: str | None = None) -> None:
    exif = Image.Exif()
    exif[0x0110] = "NBE-Demo Scanner S1"            # Model
    if software:
        exif[0x0131] = software                       # Software
    img.save(path, "JPEG", quality=quality, exif=exif.tobytes())


def jpeg_roundtrip(img: Image.Image, quality: int) -> Image.Image:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


@dataclass
class Applicant:
    id: str
    name_ar: str
    name_en: str
    nid_last4: str
    nid_masked: str
    address_ar: str
    employer_ar: str
    employer_en: str
    job_ar: str
    salary: int
    hire: str
    sme: bool
    business_ar: str = ""
    loan_amount: int = 0
    docs: list = field(default_factory=list)


NAMES = [("أحمد محمود عبد الرحمن", "Ahmed Mahmoud Abdelrahman"), ("منى سامي الشريف", "Mona Samy El-Sherif"),
         ("يوسف خالد النجار", "Youssef Khaled El-Naggar"), ("سارة إبراهيم فوزي", "Sara Ibrahim Fawzy"),
         ("عمر طارق حسنين", "Omar Tarek Hassanein"), ("ليلى مصطفى عزت", "Laila Mostafa Ezzat"),
         ("كريم وائل منصور", "Karim Wael Mansour"), ("هدى أشرف رضوان", "Hoda Ashraf Radwan")]
STREETS = ["شارع التحرير، الدقي، الجيزة", "شارع مصطفى النحاس، مدينة نصر، القاهرة", "طريق الحرية، سموحة، الإسكندرية",
           "شارع الجمهورية، المنصورة", "شارع 9، المعادي، القاهرة", "شارع الهرم، الجيزة", "شارع فؤاد، محطة الرمل، الإسكندرية",
           "شارع النصر، المعادي الجديدة، القاهرة"]
EMPLOYERS = [("شركة النيل للصناعات الغذائية التجريبية", "Nile Foods (Sample) Co."), ("مجموعة الدلتا للمقاولات التجريبية", "Delta Contracting (Sample) Group"),
             ("شركة الأفق للبرمجيات التجريبية", "Horizon Software (Sample)"), ("مستشفى الشفاء التجريبي", "Al-Shifa Hospital (Sample)"),
             ("شركة القاهرة للنقل التجريبية", "Cairo Transport (Sample) Co."), ("مدارس المستقبل التجريبية", "Future Schools (Sample)"),
             ("شركة البحر الأحمر للسياحة التجريبية", "Red Sea Tourism (Sample)"), ("مصنع الإسكندرية للنسيج التجريبي", "Alex Textiles (Sample)")]
JOBS = ["محاسب أول", "مهندسة مدنية", "مطور برمجيات", "صيدلانية", "مدير عمليات", "معلمة لغة إنجليزية", "مشرف مبيعات", "مديرة جودة"]
BUSINESSES = ["مخبز النور", "ورشة الأمل لصيانة السيارات", "مكتبة المعرفة", "محل الياسمين للملابس"]


def make_applicants(rng: random.Random) -> list[Applicant]:
    out = []
    for i, ((na, ne), street, (ea, ee), job) in enumerate(zip(NAMES, STREETS, EMPLOYERS, JOBS)):
        last4 = f"{rng.randint(1000, 9999)}"
        out.append(Applicant(
            id=f"A{i + 1:02d}", name_ar=na, name_en=ne, nid_last4=last4, nid_masked=f"2{rng.randint(80, 99)}XXXXXXXX{last4}",
            address_ar=f"{rng.randint(3, 120)} {street}", employer_ar=ea, employer_en=ee, job_ar=job,
            salary=rng.choice([9500, 12800, 14200, 18500, 21000, 26500, 31000, 15750]), hire=f"20{rng.randint(12, 22)}-0{rng.randint(1, 9)}-01",
            sme=i >= 4, business_ar=BUSINESSES[i - 4] if i >= 4 else "", loan_amount=rng.choice([150, 250, 400, 600]) * 1000))
    return out


def doc_national_id(a: Applicant, rng: random.Random) -> tuple[Image.Image, dict]:
    img = Image.new("RGB", (1240, 780), (236, 242, 238))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((20, 20, 1220, 760), 30, outline=(60, 90, 80), width=4)
    ar(d, 1180, 50, "بطاقة هوية تجريبية للعرض", 40, True)
    en(d, 60, 62, "DEMO IDENTITY CARD · NOT AN OFFICIAL DOCUMENT", 22, True, fill=(150, 30, 30))
    photo = (70, 170, 370, 560)
    avatar(img, photo, rng)
    rows = [("الاسم", a.name_ar), ("العنوان", a.address_ar), ("الرقم القومي (مقنّع)", a.nid_masked), ("تاريخ الإصدار", "2023/05/14")]
    y = 180
    fields = {}
    for label, val in rows:
        ar(d, 1180, y, label + ":", 28, True)
        box = ar(d, 1180 - 260, y, val, 30)
        fields[label] = box
        y += 95
    specimen(img)
    return img, {"photo": photo, "fields": fields}


def doc_utility_bill(a: Applicant, rng: random.Random, period: str) -> tuple[Image.Image, dict]:
    img = Image.new("RGB", (W, H), "white")
    d = header(img, "فاتورة استهلاك كهرباء", "شركة الكهرباء التجريبية لجنوب القاهرة", "Sample Electricity Co. (fictitious)", (20, 70, 140))
    acct = f"{rng.randint(10_000_000, 99_999_999)}"
    kwh = rng.randint(180, 640)
    amount = round(kwh * 1.68 + 24.5, 2)
    rows = [("اسم المشترك", a.name_ar), ("عنوان التركيب", a.address_ar), ("رقم الحساب", acct), ("فترة الاستهلاك", period),
            ("الاستهلاك (ك.و.س)", str(kwh)), ("المبلغ المستحق (جنيه)", f"{amount:,.2f}")]
    y, boxes = 320, {}
    for label, val in rows:
        ar(d, W - 80, y, label + ":", 30, True)
        boxes[label] = ar(d, W - 480, y, val, 30)
        y += 90
    ar(d, W - 80, y + 60, "يرجى السداد خلال 15 يوماً من تاريخ الإصدار.", 26, fill=(90, 90, 90))
    specimen(img)
    return img, {"fields": boxes, "amount": amount, "account": acct}


def doc_hr_letter(a: Applicant, rng: random.Random, date: str, salary: int | None = None, employer_ar: str | None = None):
    img = Image.new("RGB", (W, H), "white")
    emp_ar = employer_ar or a.employer_ar
    d = header(img, "خطاب تعريف بالراتب", emp_ar, a.employer_en, (90, 50, 20))
    sal = salary if salary is not None else a.salary
    ar(d, W - 80, 320, f"التاريخ: {date.replace('-', '/')}", 30)
    ar(d, W - 80, 400, "إلى السادة / البنك الأهلي المصري", 30, True)
    ar(d, W - 80, 470, "تحية طيبة وبعد،", 30)
    lines = [f"تشهد {emp_ar} بأن السيد/ة: {a.name_ar}،",
             f"رقم قومي ينتهي بـ {a.nid_last4}، يعمل/تعمل لديها بوظيفة {a.job_ar}",
             f"منذ {a.hire.replace('-', '/')}، ويتقاضى راتباً شهرياً إجمالياً قدره:"]
    y = 560
    for ln in lines:
        ar(d, W - 80, y, ln, 30)
        y += 70
    sal_box = ar(d, W - 80, y, f"{sal:,} جنيه مصري", 34, True)
    y += 110
    ar(d, W - 80, y, "وقد أُعطي هذا الخطاب بناءً على طلبه دون أدنى مسؤولية على الشركة.", 28)
    ar(d, W - 80, y + 160, "مدير الموارد البشرية", 30, True)
    signature(d, W - 420, y + 250, rng)
    st = stamp(img, 300, y + 230, "الموارد البشرية")
    specimen(img)
    return img, {"salary_box": sal_box, "stamp": st, "date_y": 320, "salary": sal}


def doc_bank_statement(a: Applicant, rng: random.Random, salary_credit: int, payer_ar: str | None = None):
    img = Image.new("RGB", (W, H), "white")
    d = header(img, "كشف حساب - آخر ثلاثة أشهر", "بنك النماء التجريبي", "Al-Namaa Sample Bank (fictitious)", (110, 20, 60))
    ar(d, W - 80, 310, f"اسم العميل: {a.name_ar}", 30)
    ar(d, W - 80, 370, f"رقم الحساب: {rng.randint(1000, 9999)}-XXXX-{rng.randint(1000, 9999)}", 30)
    cols = [W - 80, W - 360, W - 800, 260]
    ar(d, cols[0], 460, "التاريخ", 28, True)
    ar(d, cols[1], 460, "البيان", 28, True)
    ar(d, cols[3], 460, "دائن (جنيه)", 28, True)
    d.line((60, 510, W - 60, 510), fill=(120, 120, 120), width=2)
    y, rows = 530, []
    payer = payer_ar or a.employer_ar
    for m in ("2026-06", "2026-07", "2026-08"):
        days = sorted(rng.sample(range(1, 29), 3))
        entries = [(f"تحويل راتب - {payer}", salary_credit), ("إيداع نقدي", rng.randint(500, 3000)),
                   ("خصم بطاقة - مشتريات", -rng.randint(300, 2500))]
        for day, (desc, amt) in zip(days, entries):
            ar(d, cols[0], y, f"{m}-{day:02d}".replace("-", "/"), 26)
            ar(d, cols[1], y, desc, 24)
            box = ar(d, cols[3], y, f"{amt:,}" if amt > 0 else f"({-amt:,})", 26)
            rows.append({"month": m, "desc": desc, "amount": amt, "box": box})
            y += 60
    specimen(img)
    return img, {"rows": rows}


def doc_commercial_register(a: Applicant, rng: random.Random, expiry: str):
    img = Image.new("RGB", (W, H), "white")
    d = header(img, "مستخرج سجل تجاري (نموذج تجريبي)", "مكتب السجل التجاري التجريبي", "Sample Commercial Registry (fictitious)", (60, 60, 60))
    reg = f"{rng.randint(100000, 999999)}"
    rows = [("اسم المنشأة", a.business_ar), ("اسم المالك", a.name_ar), ("رقم السجل", reg), ("النشاط", "تجارة وخدمات"),
            ("العنوان", a.address_ar), ("تاريخ القيد", "2019/02/11"), ("تاريخ انتهاء الصلاحية", expiry.replace("-", "/"))]
    y, boxes = 320, {}
    for label, val in rows:
        ar(d, W - 80, y, label + ":", 30, True)
        boxes[label] = ar(d, W - 460, y, val, 30)
        y += 90
    st = stamp(img, 330, y + 160, "السجل التجاري")
    specimen(img)
    return img, {"fields": boxes, "stamp": st, "register_no": reg}


def doc_invoice(a: Applicant, rng: random.Random, total: int | None = None):
    img = Image.new("RGB", (W, H), "white")
    d = header(img, "فاتورة ضريبية (نموذج تجريبي)", "شركة التوريدات المتحدة التجريبية", "United Supplies (Sample) Co.", (30, 100, 100))
    ar(d, W - 80, 310, f"العميل: {a.business_ar or a.name_ar}", 30)
    ar(d, W - 80, 370, f"رقم الفاتورة: INV-{rng.randint(10000, 99999)}".replace("INV-", ""), 30)
    items = [("خامات", rng.randint(5, 40), rng.randint(200, 900)), ("معدات", rng.randint(1, 4), rng.randint(3000, 12000)),
             ("نقل", 1, rng.randint(300, 1200))]
    y = 470
    subtotal = 0
    for name, qty, price in items:
        ar(d, W - 80, y, f"{name} × {qty}", 28)
        ar(d, 400, y, f"{qty * price:,}", 28)
        subtotal += qty * price
        y += 65
    vat = round(subtotal * 0.14)
    true_total = subtotal + vat
    ar(d, W - 80, y + 30, "ضريبة القيمة المضافة 14%:", 28)
    ar(d, 400, y + 30, f"{vat:,}", 28)
    tot_box = ar(d, 400, y + 110, f"{(total or true_total):,}", 32, True)
    ar(d, W - 80, y + 110, "الإجمالي (جنيه):", 32, True)
    specimen(img)
    return img, {"total_box": tot_box, "subtotal": subtotal, "vat": vat, "true_total": true_total}


def patch_text(img: Image.Image, box, new_text: str, size: int, bold: bool = False, shift_px: int = 0) -> Image.Image:
    """Forge: white-out a value and re-type it in a pasted patch, then re-compress the patch differently."""
    x0, y0, x1, y1 = box
    pad = 8
    patch = Image.new("RGB", (x1 - x0 + 2 * pad + 60, y1 - y0 + 2 * pad), "white")
    pd = ImageDraw.Draw(patch)
    ar(pd, patch.width - pad, pad + shift_px, new_text, size, bold)
    patch = jpeg_roundtrip(patch, 55)                 # different compression history -> ELA signal
    img = img.copy()
    img.paste(patch, (x1 - patch.width + pad, y0 - pad))
    return img


def build() -> dict:
    rng = random.Random(SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.jpg"):
        f.unlink()
    apps = make_applicants(rng)
    forgeries: dict[str, dict] = {}   # filename -> manipulation
    manifest = {"seed": SEED, "applicants": [], "forged_count": 0, "false_positive": None,
                "note": "Synthetic, fictitious documents with SPECIMEN watermarks. Not real people, IDs, companies or banks."}

    plan = {  # applicant -> {doc kind: forgery}
        "A01": {"hr_letter": "salary_edited"},
        "A02": {"utility_bill": "address_altered", "bank_statement": "amount_edited"},
        "A03": {"national_id": "photo_swapped"},
        # A04 is a clean pack carrying the planned false positive: one flag, which the officer clears
        "A05": {"hr_letter": "date_altered", "commercial_register": "stamp_cloned"},
        "A06": {"invoice": "total_altered_metadata"},
        "A07": {"utility_bill": "name_changed", "commercial_register": "expiry_altered"},
        "A08": {"hr_letter": "employer_mismatch"},
    }
    false_positive = ("A04", "utility_bill")   # genuine, but a heavily recompressed phone re-scan

    for a in apps:
        rec = {"id": a.id, "name_ar": a.name_ar, "name_en": a.name_en, "loan_amount_egp": a.loan_amount,
               "declared": {"salary": a.salary, "employer": a.employer_ar, "address": a.address_ar, "nid_last4": a.nid_last4},
               "documents": []}
        kinds = ["national_id", "utility_bill", "hr_letter", "bank_statement"] + (["commercial_register", "invoice"] if a.sme else [])
        # 40 documents in total: 4 for individuals and 6 for SMEs would be 40 with 4+4 split
        for kind in kinds:
            forge = plan.get(a.id, {}).get(kind)
            meta: dict = {}
            software = None
            heavy = (a.id, kind) == false_positive
            if kind == "national_id":
                img, meta = doc_national_id(a, rng)
                img = scan_look(img, rng, heavy=heavy)        # the scan exists first; a tamperer edits the scanned file
                if forge == "photo_swapped":
                    other = Image.new("RGB", (300, 390))
                    avatar(other, (0, 0, 300, 390), random.Random(999))
                    img.paste(jpeg_roundtrip(other, 50), meta["photo"][:2])
            elif kind == "utility_bill":
                img, meta = doc_utility_bill(a, rng, "2026/08")
                img = scan_look(img, rng, heavy=heavy)
                if forge == "address_altered":
                    img = patch_text(img, meta["fields"]["عنوان التركيب"], f"{rng.randint(3, 99)} شارع الثورة، مصر الجديدة، القاهرة", 30)
                elif forge == "name_changed":
                    img = patch_text(img, meta["fields"]["اسم المشترك"], "محمد عادل السيد", 30)
            elif kind == "hr_letter":
                date = "2026-09-14"
                if forge == "employer_mismatch":
                    img, meta = doc_hr_letter(a, rng, date, employer_ar="شركة الصفوة للاستثمار التجريبية")
                else:
                    img, meta = doc_hr_letter(a, rng, date)
                img = scan_look(img, rng, heavy=heavy)
                if forge == "salary_edited":
                    img = patch_text(img, meta["salary_box"], f"{a.salary + 13500:,} جنيه مصري", 34, True)
                elif forge == "date_altered":
                    d = ImageDraw.Draw(img)
                    box = d.textbbox((W - 80, 320), "التاريخ: 2026/09/14", font=font(30), anchor="ra", direction="rtl", language="ar")
                    img = patch_text(img, box, "التاريخ: 2026/12/14", 30)
            elif kind == "bank_statement":
                img, meta = doc_bank_statement(a, rng, a.salary)
                img = scan_look(img, rng, heavy=heavy)
                if forge == "amount_edited":
                    row = meta["rows"][3]   # second month's salary credit
                    img = patch_text(img, row["box"], f"{a.salary * 2:,}", 26)
            elif kind == "commercial_register":
                expiry = "2027-02-10"
                img, meta = doc_commercial_register(a, rng, expiry)
                img = scan_look(img, rng, heavy=heavy)
                if forge == "stamp_cloned":
                    region = img.crop(meta["stamp"])
                    img.paste(region, (meta["stamp"][0] + 520, meta["stamp"][1] - 40))   # copy-move
                elif forge == "expiry_altered":
                    img = patch_text(img, meta["fields"]["تاريخ انتهاء الصلاحية"], "2029/02/10", 30)
                    expiry = "2026-02-10"   # true value: already expired
            elif kind == "invoice":
                img, meta = doc_invoice(a, rng)
                img = scan_look(img, rng, heavy=heavy)
                if forge == "total_altered_metadata":
                    img = patch_text(img, meta["total_box"], f"{meta['true_total'] * 3:,}", 32, True)
                    software = "Adobe Photoshop 25.1 (Windows)"
            if heavy:
                software = "Microsoft Lens (re-saved)"
                img = jpeg_roundtrip(img, 40)
            fname = f"{a.id}_{kind}.jpg"
            save_jpeg(img, OUT / fname, quality=90, software=software)
            doc = {"file": fname, "kind": kind, "forged": bool(forge), "manipulation": forge}
            if heavy:
                doc["planned_false_positive"] = "genuine document; heavy recompression and an editing-app Software tag will raise a forensic flag"
                manifest["false_positive"] = fname
            rec["documents"].append(doc)
            if forge:
                forgeries[fname] = forge
        manifest["applicants"].append(rec)
    manifest["forged_count"] = len(forgeries)
    manifest["document_count"] = sum(len(a["documents"]) for a in manifest["applicants"])
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    m = build()
    print(f"D1: {m['document_count']} documents, {m['forged_count']} forged, false positive: {m['false_positive']}")
