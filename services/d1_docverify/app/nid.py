"""The Egyptian national ID number, decoded.

The 14 digits describe themselves: C YYMMDD GG SSSS X is the century (2: 1900s, 3: 2000s), the date of
birth, the governorate of registration, a serial whose last digit is odd for males and even for females,
and a check digit. So a number can be checked against what the card prints and what the applicant typed,
with no model involved. The check digit is not verified: its algorithm is not officially documented.
"""
from datetime import date

AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
LENGTH = 14
MALE, FEMALE = "ذكر", "أنثى"
CENTURIES = {"2": 1900, "3": 2000}
# 88 is used for births registered outside Egypt
GOVERNORATES = {"01", "02", "03", "04", "11", "12", "13", "14", "15", "16", "17", "18", "19", "21", "22", "23", "24", "25",
                "26", "27", "28", "29", "31", "32", "33", "34", "35", "88"}


def digits(value) -> str:
    """Western digits only: cards print Arabic-Indic digits and the reader echoes what it sees."""
    return "".join(c for c in str(value or "").translate(AR_DIGITS) if c.isdigit())


def inspect(value) -> tuple[dict | None, list[tuple[str, str]]]:
    """(facts, problems): what the number encodes, or why it cannot be a national ID, as (Arabic, English) pairs."""
    d = digits(value)
    if not d:
        return None, [("الرقم القومي غير مقروء", "the national ID number could not be read")]
    if len(d) != LENGTH:
        return None, [(f"الرقم القومي {len(d)} رقماً وليس 14", f"the number has {len(d)} digits, not 14")]
    problems = []
    century = CENTURIES.get(d[0])
    if century is None:
        problems.append((f"خانة القرن ({d[0]}) ليست 2 أو 3", f"century digit {d[0]} is not 2 or 3"))
    birth = None
    if century is not None:
        try:
            birth = date(century + int(d[1:3]), int(d[3:5]), int(d[5:7]))
        except ValueError:
            problems.append((f"تاريخ الميلاد داخل الرقم غير صحيح ({d[1:3]}/{d[3:5]}/{d[5:7]})",
                             f"the birth date inside the number is not a real date ({d[1:3]}/{d[3:5]}/{d[5:7]})"))
    if d[7:9] not in GOVERNORATES:
        problems.append((f"كود المحافظة ({d[7:9]}) غير معروف", f"governorate code {d[7:9]} is unknown"))
    if problems:
        return None, problems
    return {"national_id": d, "birthdate": birth.isoformat(), "gender": MALE if int(d[12]) % 2 else FEMALE}, []


def differing(a, b) -> int:
    """How many digits differ between two numbers (a different length counts as all of them)."""
    a, b = digits(a), digits(b)
    return LENGTH if len(a) != len(b) else sum(x != y for x, y in zip(a, b))
