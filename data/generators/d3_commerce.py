"""D3 synthetic commerce data (PLAN.md §4 D3): 5,000 customers, 100 merchants, 50,000 transactions.

Customers belong to personas with different category preferences, so interest profiles derived from
spending are meaningful (and checkable against `persona`). All names and merchants are fictitious.
Writes CSVs to data/generated/d3; the D3 service loads them into Postgres (schema d3).
"""
import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

OUT = Path("/repo/data/generated/d3")
SEED = 2026

CATEGORIES = {  # key: (Arabic, English, MCC, typical ticket EGP)
    "grocery": ("سوبر ماركت", "Supermarket", "5411", 650),
    "dining": ("مطاعم", "Restaurants", "5812", 420),
    "cafe": ("مقاهي", "Cafés", "5814", 120),
    "fashion": ("ملابس وأزياء", "Fashion", "5651", 900),
    "electronics": ("إلكترونيات", "Electronics", "5732", 4200),
    "travel": ("طيران وسفر", "Travel", "4511", 7800),
    "hotels": ("فنادق ومنتجعات", "Hotels", "7011", 5200),
    "fuel": ("محطات وقود", "Fuel", "5541", 600),
    "pharmacy": ("صيدليات", "Pharmacy", "5912", 280),
    "education": ("تعليم ومدارس", "Education", "8211", 6500),
    "home": ("أثاث وأدوات منزلية", "Home & furniture", "5712", 3100),
    "telecom": ("اتصالات وشحن", "Telecom & top-up", "4814", 150),
}
MERCHANT_NAMES = {
    "grocery": ["سوبر ماركت الخير", "هايبر النيل", "ماركت البركة", "أسواق الواحة", "بقالة السعادة", "هايبر الدلتا", "سوق الفرح", "ماركت الندى", "أسواق المدينة", "ماركت الأمانة"],
    "dining": ["مطعم أبو شقرة التجريبي", "مشويات الفلاح", "مطعم البحر الأزرق", "بيتزا الميدان", "كشري النجمة", "مطعم ليالي الشام", "برجر سيتي", "مطعم النخيل", "فطاطري الحسين", "مطعم الريف المصري"],
    "cafe": ["قهوة الأصدقاء", "كافيه الكورنيش", "بن الصباح", "كافيه الزمالك", "قهوة الحكاية", "كافيه المكتبة", "حلواني السكرية", "عصائر الربيع", "قهوة النيل", "كافيه الشروق"],
    "fashion": ["أزياء الياسمين", "متجر الأناقة", "بوتيك ليلى", "أحذية الخطوة", "ملابس الشباب", "أزياء النيل", "بيت الجينز", "متجر العباية", "أزياء المدينة"],
    "electronics": ["إلكترونيات المستقبل", "عالم الموبايل", "تك زون", "بيت الأجهزة", "كمبيوتر بلس", "ديجيتال هاب", "صوت وصورة", "سمارت ستور"],
    "travel": ["سما للسفر", "طيران الأفق التجريبي", "رحلات النيل", "سفريات الشروق", "حجوزات العالم", "سياحة الفراعنة", "رحلات البحر الأحمر", "مكتب الواحة للسياحة"],
    "hotels": ["منتجع العين السخنة التجريبي", "فندق الكورنيش", "منتجع الساحل", "فندق الأقصر الذهبي", "منتجع شرم بلو", "فندق الإسكندرية بالاس"],
    "fuel": ["وقود الطريق", "محطة النصر", "بترول الوادي", "محطة الصحراوي", "وقود المدينة", "محطة السلام", "وقود الدائري"],
    "pharmacy": ["صيدلية الشفاء", "صيدلية الحياة", "صيدليات العزبي التجريبية", "صيدلية النور", "صيدلية الأمل", "صيدلية الحكمة", "صيدلية الرحمة", "صيدلية الدواء"],
    "education": ["مدارس المستقبل التجريبية", "أكاديمية اللغات", "مركز التفوق", "جامعة المعرفة التجريبية", "حضانة البراعم", "مركز تدريب الإبداع", "مكتبة الطالب", "أكاديمية البرمجة"],
    "home": ["أثاث الأسرة", "بيت الديكور", "أدوات منزلية النيل", "مفروشات الراحة", "مطابخ الحديثة", "إضاءة القاهرة", "سجاد الشرق", "بيت المطبخ"],
    "telecom": ["شحن فوري", "اتصالات بلس", "خط سريع", "موبايل باي", "نت هوم", "كارت الشحن", "سيم ستور", "داتا تك"],
}
PERSONAS = {  # persona: (Arabic label, share, category weights, monthly txn count range)
    "young_professional": ("شباب الموظفين", 0.28, {"dining": 5, "cafe": 6, "electronics": 2, "travel": 1.5, "fashion": 3, "telecom": 3, "fuel": 2, "grocery": 2}, (8, 16)),
    "family": ("الأسر", 0.30, {"grocery": 8, "pharmacy": 4, "education": 2, "home": 2, "fuel": 3, "dining": 2, "telecom": 1}, (8, 14)),
    "student": ("الطلاب", 0.14, {"cafe": 7, "telecom": 6, "fashion": 3, "dining": 3, "education": 1.5, "electronics": 0.7}, (5, 10)),
    "affluent": ("كبار العملاء", 0.12, {"travel": 5, "hotels": 4, "dining": 4, "fashion": 3, "electronics": 1.5, "home": 1.5, "grocery": 2}, (10, 18)),
    "sme_owner": ("أصحاب المشروعات الصغيرة", 0.16, {"fuel": 6, "telecom": 3, "home": 2, "electronics": 2, "grocery": 3, "dining": 2}, (8, 15)),
}
CITIES = [("القاهرة", 0.38), ("الجيزة", 0.18), ("الإسكندرية", 0.16), ("المنصورة", 0.07), ("طنطا", 0.05), ("أسيوط", 0.05),
          ("الإسماعيلية", 0.04), ("الأقصر", 0.04), ("الغردقة", 0.03)]
FIRST = ["أحمد", "محمد", "محمود", "مصطفى", "عمر", "يوسف", "كريم", "خالد", "طارق", "حسن", "منى", "سارة", "نور", "ليلى", "هدى", "مريم", "ياسمين", "دينا", "رنا", "آية"]
LAST = ["حسن", "عبد الله", "السيد", "إبراهيم", "فهمي", "سليمان", "رمضان", "النجار", "الشريف", "منصور", "عزت", "رضوان", "فوزي", "عادل", "شاكر"]


def weighted(rng: random.Random, items: dict | list):
    keys, weights = (list(items), list(items.values())) if isinstance(items, dict) else zip(*items)
    return rng.choices(list(keys), weights=list(weights))[0]


def build() -> dict:
    rng = random.Random(SEED)
    OUT.mkdir(parents=True, exist_ok=True)

    merchants = []
    mid = 0
    for cat, names in MERCHANT_NAMES.items():
        ar_cat, en_cat, mcc, _ = CATEGORIES[cat]
        for name in names:
            mid += 1
            merchants.append({"id": f"M{mid:03d}", "name_ar": name, "category": cat, "category_ar": ar_cat, "category_en": en_cat,
                              "mcc": mcc, "city": weighted(rng, CITIES),
                              "description_ar": f"{name}: {ar_cat} في {weighted(rng, CITIES)}",
                              "partner": rng.random() < 0.35})   # partner merchants can carry bank offers
    assert len(merchants) == 100, len(merchants)
    by_cat: dict[str, list] = {}
    for m in merchants:
        by_cat.setdefault(m["category"], []).append(m)

    customers = []
    for i in range(1, 5001):
        persona = weighted(rng, {k: v[1] for k, v in PERSONAS.items()})
        age = {"student": (18, 24), "young_professional": (23, 34), "family": (30, 50), "affluent": (35, 65), "sme_owner": (28, 60)}[persona]
        customers.append({
            "id": f"K{i:05d}", "name_ar": f"{rng.choice(FIRST)} {rng.choice(LAST)}", "persona": persona, "persona_ar": PERSONAS[persona][0],
            "age": rng.randint(*age), "gender": rng.choice(["M", "F"]), "city": weighted(rng, CITIES),
            "income_band": {"student": "low", "young_professional": "mid", "family": "mid", "affluent": "high", "sme_owner": "mid"}[persona],
            "cards": "debit" if persona == "student" else rng.choice(["debit", "debit,credit", "credit"]),
            "lang": "ar" if rng.random() < 0.82 else "en", "opt_in_sms": rng.random() < 0.85, "opt_in_email": rng.random() < 0.55,
        })

    # 50,000 transactions over 90 days, allocated in proportion to each persona's activity
    start = datetime(2026, 6, 1)
    weights = [rng.uniform(*PERSONAS[c["persona"]][3]) for c in customers]
    owners = rng.choices(customers, weights=weights, k=50_000)
    txns = []
    for t, c in enumerate(owners, start=1):
        cat = weighted(rng, PERSONAS[c["persona"]][2])
        local = [m for m in by_cat[cat] if m["city"] == c["city"]] or by_cat[cat]
        m = rng.choice(local if rng.random() < 0.7 else by_cat[cat])
        base = CATEGORIES[cat][3] * (1.8 if c["income_band"] == "high" else 0.6 if c["income_band"] == "low" else 1)
        amount = round(max(15, rng.lognormvariate(0, 0.5) * base), 2)
        ts = start + timedelta(days=rng.randint(0, 89), hours=rng.randint(8, 23), minutes=rng.randint(0, 59))
        txns.append({"id": t, "customer_id": c["id"], "merchant_id": m["id"], "ts": ts.isoformat(), "amount": amount,
                     "channel": rng.choices(["pos", "online", "contactless"], [0.5, 0.25, 0.25])[0]})

    for name, rows in (("merchants", merchants), ("customers", customers), ("transactions", txns)):
        with open(OUT / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    return {"merchants": len(merchants), "customers": len(customers), "transactions": len(txns)}


if __name__ == "__main__":
    print("D3:", build())
