"""The national ID number, checked by the rules of the active country (nbe_core.locale.NATIONAL_ID).

Egypt (decode=True): the 14 digits describe themselves: C YYMMDD GG SSSS X is the century (2: 1900s, 3: 2000s), the date of
birth, the governorate of registration, a serial whose last digit is odd for males and even for females,
and a check digit. So a number can be checked against what the card prints and what the applicant typed,
with no model involved. The check digit is not verified: its algorithm is not officially documented.
Other countries: only the length and the leading digits are checked (Saudi 10 digits from 1 or 2, Emirates ID
15 digits from 784, Moroccan CIN digits after its letters), and nothing is decoded.
"""
from datetime import date

from nbe_core import locale as L

AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
SPEC = L.NATIONAL_ID                     # {"length": 14 | None, "prefixes": ("2", "3"), "decode": True}
LENGTH = SPEC.get("length") or 0         # 0: the length varies (Moroccan CIN), so it is not checked
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
        return None, [(f"{L.NATIONAL_ID_AR} غير مقروء", "the national ID number could not be read")]
    if LENGTH and len(d) != LENGTH:
        return None, [(f"{L.NATIONAL_ID_AR} {len(d)} رقماً وليس {LENGTH}", f"the number has {len(d)} digits, not {LENGTH}")]
    prefixes = SPEC.get("prefixes") or ()
    if prefixes and not d.startswith(tuple(prefixes)):
        return None, [(f"{L.NATIONAL_ID_AR} لا يبدأ بـ {' أو '.join(prefixes)}", f"the number does not start with {' or '.join(prefixes)}")]
    if not SPEC.get("decode"):
        return None, []                    # nothing more is encoded in it that the rules can check
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


def complete(value) -> bool:
    """A whole number (not a last-4 or a misread): the country's length, or at least 5 digits where it varies."""
    n = len(digits(value))
    return n == LENGTH if LENGTH else n >= 5


def differing(a, b) -> int:
    """How many digits differ between two numbers (a different length counts as all of them)."""
    a, b = digits(a), digits(b)
    return max(len(a), len(b)) if len(a) != len(b) else sum(x != y for x, y in zip(a, b))
