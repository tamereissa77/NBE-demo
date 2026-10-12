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


_DROP = set("ًٌٍَُِّْـ​‌‍‎‏؜﻿")  # diacritics, tatweel/kashida, zero-width and direction marks
_FOLD = {**{c: "ا" for c in "أإآٱ"}, "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي", "٪": "%", "﹪": "%", "％": "%",
         **{a: str(i) for i, a in enumerate("٠١٢٣٤٥٦٧٨٩")}, **{p: str(i) for i, p in enumerate("۰۱۲۳۴۵۶۷۸۹")}}


def normalize_map(text: str) -> tuple[str, list[int]]:
    """For rule matching: normalize_ar's folding plus Arabic/Persian digits -> ASCII, Arabic percent -> %, hamza
    carriers, zero-width marks dropped, lower case, each whitespace char -> " ". Returns the normalised text and,
    for every normalised char, its index in the original, so a match can be located (and removed) in the original."""
    out, idx = [], []
    for i, ch in enumerate(text):
        if ch in _DROP:
            continue
        out.append(" " if ch.isspace() else _FOLD.get(ch, ch).lower())
        idx.append(i)
    return "".join(out), idx
def plain_typography(text: str) -> str:
    """Models emit non-breaking hyphens, narrow no-break spaces and zero-width characters (gpt-oss most of all).
    The Arabic UI fonts have no glyphs for them and the browser cannot wrap at them, so text meant for display
    or SMS gets the plain hyphen and space instead."""
    text = re.sub("[\u2010-\u2013\u2212]", "-", text)
    text = re.sub("[\u00a0\u2007\u2009\u202f]", " ", text)
    return re.sub("[\u200b\u2060\ufeff]", "", text)


def strip_preamble(text: str) -> str:
    """Remove a leading 'Here is ...:' line and surrounding quotes that models add to drafts."""
    lines = text.strip().splitlines()
    if lines and re.match(r"^(إليك|اليك|هذا|هذه|فيما يلي|Here is|Here's|Below is)", lines[0].strip()) and lines[0].rstrip().endswith((":", "：")):
        lines = lines[1:]
    out = "\n".join(lines).strip()
    return out.strip('"“”').strip()
