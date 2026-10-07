"""Arabic-aware text helpers."""
import re

AR = re.compile(r"[؀-ۿ]")
LATIN = re.compile(r"[A-Za-z]")


def arabic_ratio(text: str) -> float:
    a, l = len(AR.findall(text)), len(LATIN.findall(text))
    return a / max(a + l, 1)


def detect_lang(text: str) -> str:
    """'ar' or 'en' by script (mixed Arabic/English text counts as Arabic when Arabic dominates)."""
    return "ar" if arabic_ratio(text) >= 0.4 else "en"


def normalize_ar(text: str) -> str:
    """For matching: strip diacritics and tatweel, unify alef/ya/ta-marbuta forms, collapse spaces."""
    text = re.sub(r"[ً-ْـ]", "", text)
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي").replace("ة", "ه")
    return re.sub(r"\s+", " ", text).strip()


def strip_preamble(text: str) -> str:
    """Remove a leading 'Here is ...:' line and surrounding quotes that models add to drafts."""
    lines = text.strip().splitlines()
    if lines and re.match(r"^(إليك|اليك|هذا|هذه|فيما يلي|Here is|Here's|Below is)", lines[0].strip()) and lines[0].rstrip().endswith((":", "：")):
        lines = lines[1:]
    out = "\n".join(lines).strip()
    return out.strip('"“”').strip()
