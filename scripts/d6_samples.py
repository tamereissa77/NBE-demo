"""D6's sample files for each country: services/d6_assistant/app/samples/<CC>/ from the Egyptian ones in samples/.

    docker run --rm -v .:/repo -w /repo --entrypoint python nbe-d6:<tag> scripts/d6_samples.py

The samples (a policy, meeting minutes, an e-mail thread, a complaints CSV and a loans workbook) were written for
Egypt. Here each country gets the same files with its own cities, branch staff, currency and wording, so a suggested
D6 request shows that country's data. The numbers stay the same, so the answers keep the same shape. D6 serves
samples/<COUNTRY>/ when it exists, and samples/ (Egypt) otherwise. Run it again after changing an Egyptian sample.
"""
import csv
import io
import re
from pathlib import Path

import openpyxl

SAMPLES = Path(__file__).resolve().parent.parent / "services" / "d6_assistant" / "app" / "samples"
TEXTS = ["policy_ar.md", "meeting_ar.txt", "thread_ar.txt", "complaints_ar.csv"]

# Egyptian -> local. Longer keys first, so "Cairo Main" is replaced before "Cairo".
COUNTRIES = {
    "MA": {
        "ar": {"القاهرة": "الدار البيضاء", "الإسكندرية": "الرباط", "الجيزة": "مراكش", "المنصورة": "فاس",
               "جنيهاً": "درهماً", "جنيه": "درهم",
               "هاني منصور": "هشام لحلو", "منى كامل": "نادية الكتاني", "شريف لطفي": "يوسف العمراني",
               "نهى سليم": "سلمى بنكيران", "تامر عبد الله": "رشيد بوزيد",
               "بالدور الخامس": "بالطابق الخامس", "برجاء": "المرجو",
               "الأحد 4 أكتوبر 2026": "الاثنين 5 أكتوبر 2026", "الأحد 8 نوفمبر 2026": "الاثنين 9 نوفمبر 2026"},
        "en": {"Cairo Main": "Casablanca Main", "Cairo": "Casablanca", "Alexandria": "Rabat", "Giza": "Marrakech",
               "Mansoura": "Fes", "Tanta": "Tangier", "Aswan": "Agadir", "EGP": "MAD",
               "Hany": "Hicham", "Mona": "Nadia", "Sherif": "Youssef", "Noha": "Salma", "Tamer": "Rachid", "Heba": "Hiba",
               "Mansour": "Lahlou", "Kamel": "Kettani", "Lotfy": "Amrani", "Selim": "Benkirane", "Abdallah": "Bouzid",
               "Fathy": "Alaoui", "Hegazy": "Bennani", "Nabil": "Tazi", "Saad": "Berrada", "Amin": "El Fassi",
               "Zaki": "Chraibi", "Shaker": "Idrissi", "Ibrahim": "Benjelloun", "Farouk": "Sqalli"},
    },
    "SA": {
        "ar": {"القاهرة": "الرياض", "الإسكندرية": "جدة", "الجيزة": "الدمام", "المنصورة": "مكة المكرمة",
               "جنيهاً": "ريالاً", "جنيه": "ريال",
               "هاني منصور": "فهد القحطاني", "منى كامل": "نورة العتيبي", "شريف لطفي": "خالد الغامدي",
               "نهى سليم": "سارة الزهراني", "تامر عبد الله": "عبدالله الحربي",
               "برجاء": "نأمل"},
        "en": {"Cairo Main": "Riyadh Main", "Cairo": "Riyadh", "Alexandria": "Jeddah", "Giza": "Dammam",
               "Mansoura": "Makkah", "Tanta": "Madinah", "Aswan": "Abha", "EGP": "SAR",
               "Hany": "Fahad", "Mona": "Noura", "Sherif": "Khalid", "Noha": "Sara", "Tamer": "Abdullah", "Heba": "Hind",
               "Dina": "Reem", "Laila": "Lama", "Karim": "Faisal", "Nour": "Nawaf", "Hassan": "Saud",
               "Mansour": "Al-Qahtani", "Kamel": "Al-Otaibi", "Lotfy": "Al-Ghamdi", "Selim": "Al-Zahrani",
               "Abdallah": "Al-Harbi", "Fathy": "Al-Dosari", "Hegazy": "Al-Shehri", "Nabil": "Al-Mutairi",
               "Saad": "Al-Subaie", "Amin": "Al-Anazi", "Zaki": "Al-Malki", "Shaker": "Al-Shammari",
               "Ibrahim": "Al-Juhani", "Farouk": "Al-Rashidi"},
    },
    "AE": {
        "ar": {"القاهرة": "دبي", "الإسكندرية": "أبوظبي", "الجيزة": "الشارقة", "المنصورة": "العين",
               "جنيهاً": "درهماً", "جنيه": "درهم",
               "هاني منصور": "راشد المنصوري", "منى كامل": "مريم الحمادي", "شريف لطفي": "سعيد النعيمي",
               "نهى سليم": "فاطمة الكتبي", "تامر عبد الله": "عبدالله الشامسي",
               "برجاء": "يرجى", "الأحد 4 أكتوبر 2026": "الاثنين 5 أكتوبر 2026", "الأحد 8 نوفمبر 2026": "الاثنين 9 نوفمبر 2026"},
        "en": {"Cairo Main": "Dubai Main", "Cairo": "Dubai", "Alexandria": "Abu Dhabi", "Giza": "Sharjah",
               "Mansoura": "Al Ain", "Tanta": "Ajman", "Aswan": "Fujairah", "EGP": "AED",
               "Hany": "Rashid", "Mona": "Maryam", "Sherif": "Saeed", "Noha": "Fatima", "Tamer": "Abdulla", "Heba": "Hessa",
               "Dina": "Shamma", "Laila": "Latifa", "Karim": "Hamdan", "Nour": "Mansour", "Hassan": "Sultan",
               "Mansour": "Al Mansoori", "Kamel": "Al Hammadi", "Lotfy": "Al Nuaimi", "Selim": "Al Ketbi",
               "Abdallah": "Al Shamsi", "Fathy": "Al Mazrouei", "Hegazy": "Al Dhaheri", "Nabil": "Al Falasi",
               "Saad": "Al Suwaidi", "Amin": "Al Marzooqi", "Zaki": "Al Kaabi", "Shaker": "Al Zaabi",
               "Ibrahim": "Al Blooshi", "Farouk": "Al Hosani"},
    },
}


def swap(text: str, table: dict, words: bool) -> str:
    """Replace every key at once (so a replacement is never replaced again), longest first."""
    keys = sorted(table, key=len, reverse=True)
    pattern = "|".join((rf"\b{re.escape(k)}\b" if words else re.escape(k)) for k in keys)
    return re.sub(pattern, lambda m: table[m.group(0)], text)


def main() -> None:
    for code, maps in COUNTRIES.items():
        out = SAMPLES / code
        out.mkdir(exist_ok=True)
        for name in TEXTS:
            text = (SAMPLES / name).read_text(encoding="utf-8-sig" if name.endswith(".csv") else "utf-8")
            new = swap(text, maps["ar"], words=False)
            if name.endswith(".csv"):
                list(csv.reader(io.StringIO(new)))       # still a valid CSV
                (out / name).write_text(new, encoding="utf-8-sig")
            else:
                (out / name).write_text(new, encoding="utf-8")
        wb = openpyxl.load_workbook(SAMPLES / "branch_loans.xlsx")
        for ws in wb:
            for row in ws.iter_rows():
                for cell in row:
                    if isinstance(cell.value, str):
                        cell.value = swap(cell.value, maps["en"], words=True)
        wb.save(out / "branch_loans.xlsx")
        left = [w for w in ("جنيه", "القاهرة", "الإسكندرية", "الجيزة", "المنصورة", "EGP", "Cairo", "Giza")
                if any(w in (out / n).read_text(encoding="utf-8-sig") for n in TEXTS)]
        print(f"{code}: {out.relative_to(SAMPLES.parent.parent.parent.parent)}" + (f"  STILL EGYPTIAN: {left}" if left else ""))


if __name__ == "__main__":
    main()
