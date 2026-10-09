"""How D4 text is prepared for the voice (the listen button on each message and spoken replies).

An operator edits /data/seed/d4/pronunciation.ini by ear; it is re-read whenever it changes:
- [ar] and [en]: "written = spoken", banking terms respelled for a sentence in that language.
- [diacritics]: "word = the same word with diacritics". The voice engine deletes diacritics from the text
  and adds back only those in its own lexicon, so these go to it as a lexicon, not in the text.
- [wording]: words the agent should not use at all, replaced in the reply itself.

On top of that, in Arabic, amounts of money are spelled out the way they are said in Egypt ("500 جنيه" is
خمسميت جنيه, not خمسمية), and numbers that are identifiers rather than amounts (card endings, one-time codes,
ticket and handoff numbers, phone numbers) are spaced out so the voice reads them digit by digit.
"""
import configparser
import re
from pathlib import Path

TERMS_FILE = Path("/data/seed/d4/pronunciation.ini")
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
NUMBER = re.compile(r"\d[\d,.]*\d|\d")
PHONE = re.compile(r"\+\d[\d\sXx*]{6,}\d")          # +20 109 XXX 7891: masked digits are skipped
# A unit right after a long number makes it an amount ("5000 جنيه", "12000 EGP"), read as a number
UNIT = re.compile(r"\s*(جنيه|جنيها|جنيهاً|جنيهات|دولار|يورو|ريال|EGP|USD|EUR|SAR|pounds?|dollars?|euros?|%|٪)", re.I)
MONEY = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?\s*(جنيهات|جنيهاً|جنيها|جنيه|دولار|يورو|ريال|قرش)(?!\w)")
ARABIC_WORD = re.compile(r"[ء-ي]+")
_cache: tuple[float, dict[str, list[tuple[re.Pattern, str]]], dict[str, str]] = (0.0, {}, {})

# Egyptian Arabic numbers. A hundred that stands right before what it counts ends in ت: ميت جنيه, خمسميت ألف.
ONES = ["", "واحد", "اتنين", "تلاتة", "أربعة", "خمسة", "ستة", "سبعة", "تمانية", "تسعة", "عشرة",
        "حداشر", "اتناشر", "تلتاشر", "أربعتاشر", "خمستاشر", "ستاشر", "سبعتاشر", "تمنتاشر", "تسعتاشر"]
TENS = ["", "", "عشرين", "تلاتين", "أربعين", "خمسين", "ستين", "سبعين", "تمانين", "تسعين"]
HUNDREDS = ["", "مية", "ميتين", "تلتمية", "ربعمية", "خمسمية", "ستمية", "سبعمية", "تمنمية", "تسعمية"]
FEW = ["", "", "", "تلات", "أربع", "خمس", "ست", "سبع", "تمن", "تسع", "عشر"]        # 3 to 10 before تلاف
# How the hundreds must be vowelled. Bare, the voice reads ميت as مَيِّت and ميتين as مَيتين.
NUMERALS = {"مية": "مِيَّة", "ميت": "مِيت", "ميتين": "مِيتِين",
            "تلتمية": "تُلْتُمِيَّة", "تلتميت": "تُلْتُمِيت", "ربعمية": "رُبْعُمِيَّة", "ربعميت": "رُبْعُمِيت",
            "خمسمية": "خُمْسُمِيَّة", "خمسميت": "خُمْسُمِيت", "ستمية": "سُتُمِيَّة", "ستميت": "سُتُمِيت",
            "سبعمية": "سُبْعُمِيَّة", "سبعميت": "سُبْعُمِيت", "تمنمية": "تُمْنُمِيَّة", "تمنميت": "تُمْنُمِيت",
            "تسعمية": "تُسْعُمِيَّة", "تسعميت": "تُسْعُمِيت"}


def _below_1000(n: int, counting: bool) -> str:
    """0 < n < 1000; `counting` when the counted thing follows directly."""
    hundreds, rest = divmod(n, 100)
    parts = [HUNDREDS[hundreds]] if hundreds else []
    if rest:
        parts.append(ONES[rest] if rest < 20 else (ONES[rest % 10] + " و" if rest % 10 else "") + TENS[rest // 10])
    elif counting and hundreds != 2:
        parts[-1] = parts[-1][:-1] + "ت"
    return " و".join(parts)


def egyptian_number(n: int, counting: bool = False) -> str:
    """`n` in Egyptian Arabic words, up to hundreds of millions."""
    if n == 0:
        return "صفر"
    millions, rest = divmod(n, 1_000_000)
    thousands, units = divmod(rest, 1000)
    parts = []
    if millions:
        parts.append("مليون" if millions == 1 else f"{ONES[millions] if millions <= 10 else _below_1000(millions, True)} مليون")
    if thousands:
        parts.append("ألف" if thousands == 1 else "ألفين" if thousands == 2 else
                     f"{FEW[thousands]} تلاف" if thousands <= 10 else f"{_below_1000(thousands, True)} ألف")
    if units:
        parts.append(_below_1000(units, counting))
    return " و".join(parts)


def _money(m: re.Match) -> str:
    whole, piastres, unit = int(m.group(1).replace(",", "")), int((m.group(2) or "0").ljust(2, "0")), m.group(3)
    pound = unit.startswith("جنيه")
    if piastres and not pound:
        return m.group(0)                   # only pounds have a spoken name for the fraction
    name = "جنيه" if pound else unit
    spoken = f"{name} واحد" if whole == 1 else f"{egyptian_number(whole, counting=True)} {name}"
    return f"{spoken} و{egyptian_number(piastres, counting=True)} قرش" if piastres else spoken


def _file() -> tuple[dict[str, list[tuple[re.Pattern, str]]], dict[str, str]]:
    """(replacement rules per section, longest term first; the [diacritics] words). Re-read when the file changes."""
    global _cache
    try:
        mtime = TERMS_FILE.stat().st_mtime
    except OSError:
        return {}, {}
    if mtime != _cache[0]:
        cp = configparser.ConfigParser(delimiters=("=",), comment_prefixes=("#",), interpolation=None)
        cp.optionxform = str                      # keep the terms' case
        cp.read(TERMS_FILE, encoding="utf-8")
        table = {}
        for section in cp.sections():
            if section == "diacritics":
                continue
            rules = []
            for written, spoken in sorted(cp[section].items(), key=lambda kv: -len(kv[0])):
                if section == "wording":
                    rules.append((re.compile(re.escape(written)), spoken))       # also inside a word: هنتحقق -> هنتأكد
                    continue
                # Latin terms may be glued to an Arabic prefix (الOTP), so only Latin neighbours break a match.
                # ALL-CAPS terms are acronyms and match exactly; other terms match in any case (debit, Debit).
                latin = bool(re.fullmatch(r"[\x00-\x7F]+", written))
                edge = "A-Za-z0-9" if latin else r"\w"
                rules.append((re.compile(f"(?<![{edge}]){re.escape(written)}(?![{edge}])", 0 if written.isupper() else re.I), spoken))
            table[section] = rules
        # The engine looks words up one bare Arabic token at a time: anything else could never match
        marked = {w: v for w, v in (cp["diacritics"].items() if cp.has_section("diacritics") else ()) if ARABIC_WORD.fullmatch(w)}
        _cache = (mtime, table, marked)
    return _cache[1], _cache[2]


def lexicon() -> dict[str, str]:
    """{bare word: word with diacritics} for the voice engine: the number words plus the file's [diacritics]."""
    return {**NUMERALS, **_file()[1]}


def careful(spoken: str) -> bool:
    """Whether `spoken` (the output of normalize) holds a word the fast voice setting gets wrong: one of the
    file's [diacritics] words. They are listed because they were heard wrong, and vowels alone did not fix them."""
    words = _file()[1]
    return any(w in words for w in ARABIC_WORD.findall(spoken))


def _digits(m: re.Match) -> str:
    token = m.group(0)
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", token):
        return token.replace(",", "")          # 20,000 was read as "twenty ... zero": drop the thousands separators
    if len(token) < 4 or not token.isdigit() or UNIT.match(m.string, m.end()):
        return token
    # Digit by digit; long numbers in threes with a pause between, or the voice runs them together
    groups = [token] if len(token) <= 4 else [token[i:i + 3] for i in range(0, len(token), 3)]
    return ", ".join(" ".join(g) for g in groups)


def reword(text: str) -> str:
    """The reply itself with the file's [wording] replacements: what is shown as well as what is spoken."""
    for pattern, better in _file()[0].get("wording", []):
        text = pattern.sub(better, text)
    return text


def normalize(text: str, lang: str) -> str:
    """`text` as it should be handed to the TTS engine, for a sentence in `lang` (ar | en)."""
    text = re.sub(r"[*#_`]", "", text).translate(AR_DIGITS)          # Markdown marks are not spoken
    text = re.sub(r"[()\[\]]", " ", text)                               # nor are brackets, and the voice skipped what was inside
    text = re.sub(r"(?<=[A-Za-z0-9])-(?=\d)", ", ", text)              # T-261008-17063 -> T, 261008, 17063
    text = PHONE.sub(lambda m: " ".join(re.sub(r"\D", "", m.group(0))), text)
    for pattern, spoken in _file()[0].get(lang, []):                 # before the amounts: EGP becomes جنيه first
        text = pattern.sub(spoken, text)
    if lang == "ar":
        text = MONEY.sub(_money, text)
    text = NUMBER.sub(_digits, text)
    return re.sub(r"[ \t]+", " ", text).strip()
