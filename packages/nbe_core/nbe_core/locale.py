"""Locale pack: everything country-specific that the services and data generators use.

Like brand/, this file differs per bank branch: main = Egypt (NBE), Riyadh-Bank = Saudi Arabia.
Keep the names and shapes identical across branches; only the values change. All lists are synthetic
(fictitious people, companies and merchants).
"""

COUNTRY = "EG"
COUNTRY_EN, COUNTRY_AR = "Egypt", "مصر"
ADJ_EN, ADJ_AR = "Egyptian", "مصري"                   # "an Egyptian bank" / "بنك مصري"
CURRENCY, CURRENCY_AR = "EGP", "جنيه"                 # amounts: "1,000 جنيه" / "EGP 1,000"
CURRENCY_LONG_AR = "جنيه مصري"
DIALECT_EN, DIALECT_AR = "Egyptian dialect", "العامية المصرية"
NATIONAL_ID_AR = "الرقم القومي"                        # "آخر 4 أرقام من الرقم القومي"

# ------------------------------------------------------------------ prompts
# Tone for the voice/chat agent (D4) and the dialect used in social posts (D3)
AGENT_TONE = "For Arabic (including Egyptian dialect), reply in simple Modern Standard Arabic with a friendly Egyptian tone"
SOCIAL_STYLE_AR = "بالعامية المصرية المهذبة"
DINING_SCENE = "a warm elegant restaurant table with Egyptian grilled food"
RESORT_SCENE = "a luxury Red Sea resort pool with palm trees"

# D2 suggested questions (lang "dia" = local dialect). Values must match data/generators/specs.py.
D2_SUGGESTED = [
    {"lang": "ar", "q": "ما رسوم استبدال بطاقة الائتمان المفقودة الآن؟ وهل تغيّرت؟"},
    {"lang": "dia", "q": "لو العميل عايز يرفع حد التحويل لـ 150 ألف، يعمل إيه؟"},
    {"lang": "ar", "q": "ما المستندات المطلوبة للتمويل الشخصي للموظفين؟"},
    {"lang": "en", "q": "What is the commission on outgoing international transfers?"},
    {"lang": "ar", "q": "هل يمكن إرسال البطاقة البديلة إلى منزل العميل بالبريد؟"},
]

# ------------------------------------------------------------------ mock bank (D4)
MOCKBANK_FIRST = [("أحمد", "Ahmed"), ("محمد", "Mohamed"), ("منى", "Mona"), ("سارة", "Sara"), ("يوسف", "Youssef"),
                  ("ليلى", "Laila"), ("عمر", "Omar"), ("نور", "Nour"), ("خالد", "Khaled"), ("هدى", "Hoda")]
MOCKBANK_LAST = [("حسن", "Hassan"), ("عبد الله", "Abdallah"), ("السيد", "El-Sayed"), ("مصطفى", "Mostafa"),
                 ("إبراهيم", "Ibrahim"), ("فهمي", "Fahmy"), ("سليمان", "Soliman"), ("رمضان", "Ramadan")]
MOCKBANK_CITIES = ["القاهرة", "الإسكندرية", "الجيزة", "المنصورة", "أسيوط"]
PHONE_MASK = "+20 10{d} XXX {n4}"                     # masked, fictitious; {d} one digit, {n4} four digits
BALANCE_RANGE = (1_500, 450_000)

# ------------------------------------------------------------------ D1 loan packs
D1_NAMES = [("أحمد محمود عبد الرحمن", "Ahmed Mahmoud Abdelrahman"), ("منى سامي الشريف", "Mona Samy El-Sherif"),
            ("يوسف خالد النجار", "Youssef Khaled El-Naggar"), ("سارة إبراهيم فوزي", "Sara Ibrahim Fawzy"),
            ("عمر طارق حسنين", "Omar Tarek Hassanein"), ("ليلى مصطفى عزت", "Laila Mostafa Ezzat"),
            ("كريم وائل منصور", "Karim Wael Mansour"), ("هدى أشرف رضوان", "Hoda Ashraf Radwan")]
D1_STREETS = ["شارع التحرير، الدقي، الجيزة", "شارع مصطفى النحاس، مدينة نصر، القاهرة", "طريق الحرية، سموحة، الإسكندرية",
              "شارع الجمهورية، المنصورة", "شارع 9، المعادي، القاهرة", "شارع الهرم، الجيزة", "شارع فؤاد، محطة الرمل، الإسكندرية",
              "شارع النصر، المعادي الجديدة، القاهرة"]
D1_EMPLOYERS = [("شركة النيل للصناعات الغذائية التجريبية", "Nile Foods (Sample) Co."), ("مجموعة الدلتا للمقاولات التجريبية", "Delta Contracting (Sample) Group"),
                ("شركة الأفق للبرمجيات التجريبية", "Horizon Software (Sample)"), ("مستشفى الشفاء التجريبي", "Al-Shifa Hospital (Sample)"),
                ("شركة القاهرة للنقل التجريبية", "Cairo Transport (Sample) Co."), ("مدارس المستقبل التجريبية", "Future Schools (Sample)"),
                ("شركة البحر الأحمر للسياحة التجريبية", "Red Sea Tourism (Sample)"), ("مصنع الإسكندرية للنسيج التجريبي", "Alex Textiles (Sample)")]
D1_JOBS = ["محاسب أول", "مهندسة مدنية", "مطور برمجيات", "صيدلانية", "مدير عمليات", "معلمة لغة إنجليزية", "مشرف مبيعات", "مديرة جودة"]
D1_BUSINESSES = ["مخبز النور", "ورشة الأمل لصيانة السيارات", "مكتبة المعرفة", "محل الياسمين للملابس"]
D1_SALARIES = [9500, 12800, 14200, 18500, 21000, 26500, 31000, 15750]
D1_LOAN_THOUSANDS = [150, 250, 400, 600]
D1_SALARY_FORGERY_DELTA = 13500                         # added to the salary on the forged HR letter


def d1_nid_masked(rng, last4: str) -> str:
    """Masked national ID as printed on the demo card (Egyptian 14-digit layout)."""
    return f"2{rng.randint(80, 99)}XXXXXXXX{last4}"


D1_ID_CARD_TITLE = "بطاقة هوية تجريبية للعرض"
D1_HR_ID_PHRASE = "رقم قومي"                           # HR letter: "<phrase> ينتهي بـ 1234"
D1_UTILITY = {"title": "فاتورة استهلاك كهرباء", "org_ar": "شركة الكهرباء التجريبية لجنوب القاهرة",
              "kwh": (180, 640), "rate": 1.68, "fixed": 24.5}
D1_FORGED_ADDRESS = "شارع الثورة، مصر الجديدة، القاهرة"
D1_FORGED_NAME = "محمد عادل السيد"
D1_FORGED_EMPLOYER = "شركة الصفوة للاستثمار التجريبية"
D1_STATEMENT = {"cash": (500, 3000), "card": (300, 2500)}
VAT_RATE = 0.14
TAX_ID_LABEL = ""                                      # printed on the tax invoice when set (e.g. a VAT number)

# ------------------------------------------------------------------ D3 commerce
D3_TICKET = {  # typical ticket per category, in local currency
    "grocery": 650, "dining": 420, "cafe": 120, "fashion": 900, "electronics": 4200, "travel": 7800,
    "hotels": 5200, "fuel": 600, "pharmacy": 280, "education": 6500, "home": 3100, "telecom": 150,
}
D3_OFFER = {  # category -> cashback % and cap in local currency (synthetic offer rules)
    "grocery": (5, 300), "dining": (15, 250), "cafe": (20, 100), "fashion": (10, 500), "electronics": (7, 1500), "travel": (10, 2000),
    "hotels": (12, 2500), "fuel": (5, 200), "pharmacy": (8, 150), "education": (5, 1000), "home": (8, 1200), "telecom": (10, 50),
}
D3_MERCHANTS = {
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
D3_CITIES = [("القاهرة", 0.38), ("الجيزة", 0.18), ("الإسكندرية", 0.16), ("المنصورة", 0.07), ("طنطا", 0.05), ("أسيوط", 0.05),
             ("الإسماعيلية", 0.04), ("الأقصر", 0.04), ("الغردقة", 0.03)]
D3_FIRST = ["أحمد", "محمد", "محمود", "مصطفى", "عمر", "يوسف", "كريم", "خالد", "طارق", "حسن", "منى", "سارة", "نور", "ليلى", "هدى", "مريم", "ياسمين", "دينا", "رنا", "آية"]
D3_LAST = ["حسن", "عبد الله", "السيد", "إبراهيم", "فهمي", "سليمان", "رمضان", "النجار", "الشريف", "منصور", "عزت", "رضوان", "فوزي", "عادل", "شاكر"]

# ------------------------------------------------------------------ the bank's own facts (D6 drafting)
# What a drafted letter may state about the bank without being told: (label, value). Taken from the bank's public
# customer-rights brochure; to be confirmed by the bank before real use. Anything not listed here (working hours,
# addresses, fees, names of officers) is NOT known to the assistant and is left as a placeholder in a draft.
BANK_FACTS = [
    ("Call centre / مركز الاتصال", "19623"),
    ("Website / الموقع الإلكتروني", "www.nbe.com.eg"),
    ("Customer service e-mail / البريد الإلكتروني لخدمة العملاء", "customer.service@nbe.com.eg"),
    ("Fax / فاكس", "+202 25945221"),
]
WEEKEND = (4, 5)          # Friday and Saturday (Monday = 0): shown on the calendar a draft is given

# ------------------------------------------------------------------ the bank's terms (D6 translation)
# (Arabic, English): how a term is written in each language when the assistant translates. Standard banking usage,
# to be confirmed and extended by the bank; a term that is not listed is translated as the model sees fit.
GLOSSARY = [
    ("البنك الأهلي المصري", "National Bank of Egypt"), ("البنك المركزي المصري", "Central Bank of Egypt"),
    ("اعرف عميلك", "Know Your Customer (KYC)"), ("العناية الواجبة بالعملاء", "customer due diligence"),
    ("مكافحة غسل الأموال", "anti-money laundering"), ("تمويل الإرهاب", "terrorist financing"), ("الشمول المالي", "financial inclusion"),
    ("خطاب الضمان", "letter of guarantee"), ("الاعتماد المستندي", "letter of credit"), ("الأمر المستديم", "standing order"),
    ("الخصم المباشر", "direct debit"), ("بطاقة الخصم", "debit card"), ("بطاقة الائتمان", "credit card"),
    ("ماكينة الصراف الآلي", "ATM"), ("مركز الاتصال", "call centre"), ("المصروفات النثرية", "petty cash"),
    ("مدير الفرع", "Branch Manager"), ("مدير المنطقة", "Regional Manager"), ("الإدارة العليا", "senior management"),
    ("المراجعة الداخلية", "internal audit"), ("إدارة الالتزام", "Compliance Department"), ("إدارة الخزانة", "Treasury Department"),
    ("أيام عمل", "business days"), ("صراف", "teller"), ("المستفيد", "beneficiary"),
]
