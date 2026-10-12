"""How D4 text is prepared for the voice (the listen button on each message and spoken replies).

An operator edits /data/seed/d4/pronunciation.ini by ear; it is re-read whenever it changes:
- [ar] and [en]: "written = spoken", banking terms respelled for a sentence in that language.
- [diacritics]: "word = the same word with diacritics". The voice engine deletes diacritics from the text
  and adds back only those in its own lexicon, so these go to it as a lexicon, not in the text. The engine
  looks a word up exactly as written, so each word is also given behind the particles Arabic joins to it
  (المقدم، والمقدم، بمقدم، للمقدم for مقدم).
- [careful]: words that need the voice's slower, more exact setting; one word per line.
- [wording]: words the agent should not use at all, replaced in the reply itself.

On top of that, in Arabic, amounts of money are spelled out the way they are said in Egypt ("500 جنيه" is
خمسميت جنيه, not خمسمية), a half, a quarter and three quarters are said as such ("2.5 مليون" is 2 ونص مليون,
"22.5%" is 22 ونص في المية), and numbers that are identifiers rather than amounts (card endings, one-time
codes, ticket and handoff numbers, phone numbers) are spaced out so the voice reads them digit by digit.

In English every number is written out in English words. The voice's own text preparation is Arabic only: it
reads any digit it is given as an Arabic word, in an English sentence too, so for English it is switched off
(services/tts_voicetut) and no digit is left for it here.
"""
import configparser
import re
from pathlib import Path

TERMS_FILE = Path("/data/seed/d4/pronunciation.ini")
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
NUMBER = re.compile(r"\d[\d,.]*\d|\d")
PHONE = re.compile(r"\+\d[\d\sXx*]{6,}\d")          # +20 109 XXX 7891: masked digits are skipped
# A unit right after a long number makes it an amount ("5000 جنيه", "12000 EGP"), read as a number
UNIT = re.compile(r"\s*(جنيه|جنيها|جنيهاً|جنيهات|دولار|يورو|ريال|EGP|USD|EUR|SAR|(?:Egyptian |US |Saudi )?(?:pounds?|dollars?|euros?|riyals?)|%|٪)", re.I)
MONEY = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?\s*(جنيهات|جنيهاً|جنيها|جنيه|دولار|يورو|ريال|قرش)(?!\w)")
ARABIC_WORD = re.compile(r"[ء-ي]+")
# 2.5, 8.25, 0.75: said with ونص، وربع، وتلات أرباع. Any other fraction is left to the voice ("فاصلة").
FRACTION = re.compile(r"(?<![\d.,])(\d+)\.(50?|25|75)(?!\d)")
FRACTIONS = {"5": "ونص", "50": "ونص", "25": "وربع", "75": "وتلات أرباع"}
# A round hundred right before what it counts: "100 ألف" is ميت ألف. The voice would say مية ألف.
HUNDRED_OF = re.compile(r"(?<![\d.,])([1-9]00)\s+(?=(?:ألف|مليون|مليار)(?![ء-ي]))")
PERCENT = re.compile(r"\s*[%٪]")
_cache: tuple[float, dict[str, list[tuple[re.Pattern, str]]], dict[str, str], frozenset[str]] = (0.0, {}, {}, frozenset())

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
# Words this file writes for a percentage and a fraction. Bare, "في المية" came out as "في الماية" now and then.
SPOKEN = {"المية": "الْمِيَّة", "ونص": "وَنُصّ", "نص": "نُصّ", "وربع": "وَرُبْع", "ربع": "رُبْع", "وتلات": "وَتَلَات", "أرباع": "أَرْبَاع"}
# Particles written joined to the next word, and the letters that take the ل of ال into themselves
PARTICLES = {"و": "وَ", "ف": "فَ", "ب": "بِ", "ل": "لِ", "ك": "كَ"}
SUN_LETTERS = "تثدذرزسشصضطظلن"


EN_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
           "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
EN_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
EN_ORDINALS = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth", "nine": "ninth", "twelve": "twelfth"}
ORDINAL = re.compile(r"(?<![\d.,])(\d{1,3})(?:st|nd|rd|th)\b")


def english_number(n: int) -> str:
    """1250 -> one thousand two hundred fifty."""
    if n < 20:
        return EN_ONES[n]
    if n < 100:
        return EN_TENS[n // 10] + ("-" + EN_ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return EN_ONES[n // 100] + " hundred" + (" " + english_number(n % 100) if n % 100 else "")
    size, name = next((s, w) for s, w in ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")) if n >= s)
    return english_number(n // size) + " " + name + (" " + english_number(n % size) if n % size else "")


def _ordinal_en(m: re.Match) -> str:
    words = english_number(int(m.group(1)))
    last = re.search(r"[a-z]+$", words).group(0)          # only the last word changes: twenty-one -> twenty-first
    return words[:-len(last)] + (EN_ORDINALS.get(last) or (last[:-1] + "ieth" if last.endswith("y") else last + "th"))


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
    fraction = FRACTIONS.get(str(piastres))            # جنيه ونص, not جنيه وخمسين قرش
    if not whole and fraction:
        return f"{fraction[1:]} {name}"
    spoken = f"{name} واحد" if whole == 1 else f"{egyptian_number(whole, counting=True)} {name}"
    if fraction:
        return f"{spoken} {fraction}"
    return f"{spoken} و{egyptian_number(piastres, counting=True)} قرش" if piastres else spoken


def _fraction(m: re.Match) -> str:
    """2.5 -> 2 ونص. The whole part stays in digits for the voice to read, unless _digits would spell it out."""
    whole, fraction = int(m.group(1)), FRACTIONS[m.group(2)]
    if not whole:
        return fraction[1:]
    return f"{m.group(1) if whole < 1000 else egyptian_number(whole)} {fraction}"


def _forms(word: str, marked: str) -> dict[str, str]:
    """`word` with its diacritics, alone and behind و ف ب ل ك and ال, as the engine will meet it in a sentence."""
    forms = {word: marked}
    if word.startswith("ال") and len(word) > 3:              # listed with its article: only the particles are added
        stem, rest = word[2:], re.sub(r"^ال[ْ]?", "", marked)
        article = marked[2:len(marked) - len(rest)]
    else:
        stem, sun = word, word[0] in SUN_LETTERS
        vowel = 2 if "ً" <= marked[1:2] <= "ِ" else 1          # the doubling goes after the letter's own vowel
        rest = marked[:vowel] + "ّ" + marked[vowel:] if sun and "ّ" not in marked[1:3] else marked
        article = "" if sun else "ْ"
        for particle, vowelled in PARTICLES.items():
            forms[particle + word] = vowelled + marked
        for particle in "بل":
            forms["و" + particle + word] = "وَ" + PARTICLES[particle] + marked
    definite = "ال" + article + rest
    forms["ال" + stem] = definite
    for particle in "وفبك":
        forms[particle + "ال" + stem] = PARTICLES[particle] + definite
    forms["وبال" + stem] = "وَبِ" + definite
    forms["لل" + stem], forms["ولل" + stem] = "لِل" + article + rest, "وَلِل" + article + rest
    return forms


def _file() -> tuple[dict[str, list[tuple[re.Pattern, str]]], dict[str, str], frozenset[str]]:
    """(replacement rules per section, longest term first; the [diacritics] words in every joined form; the
    [careful] words likewise). Re-read when the file changes."""
    global _cache
    try:
        mtime = TERMS_FILE.stat().st_mtime
    except OSError:
        return {}, {}, frozenset()
    if mtime != _cache[0]:
        cp = configparser.ConfigParser(delimiters=("=",), comment_prefixes=("#",), interpolation=None, allow_no_value=True)
        cp.optionxform = str                      # keep the terms' case
        cp.read(TERMS_FILE, encoding="utf-8")
        table = {}
        for section in cp.sections():
            if section in ("diacritics", "careful"):
                continue
            rules = []
            for written, spoken in sorted(((w, v) for w, v in cp[section].items() if v is not None), key=lambda kv: -len(kv[0])):
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
        listed = {w: v for w, v in (cp["diacritics"].items() if cp.has_section("diacritics") else ()) if v and ARABIC_WORD.fullmatch(w)}
        marked: dict[str, str] = {}
        for word, vowelled in listed.items():
            for form, spoken in _forms(word, vowelled).items():
                marked.setdefault(form, spoken)
        marked.update(listed)                     # a form written in the file wins over one derived from another word
        slow = frozenset(form for w in (cp["careful"] if cp.has_section("careful") else ()) if ARABIC_WORD.fullmatch(w)
                         for form in _forms(w, w))
        _cache = (mtime, table, marked, slow)
    return _cache[1], _cache[2], _cache[3]


def lexicon() -> dict[str, str]:
    """{bare word: word with diacritics} for the voice engine: the number words, alone and after و or ب
    (ألف وميت جنيه), the fraction words, and the file's [diacritics]."""
    numerals = {particle + w: vowelled + v for w, v in NUMERALS.items() for particle, vowelled in (("", ""), ("و", "وَ"), ("ب", "بِ"))}
    return {**numerals, **SPOKEN, **_file()[1]}


def careful(spoken: str) -> bool:
    """Whether `spoken` (the output of normalize) holds one of the file's [careful] words: those the fast voice
    setting gets wrong even with their vowels (it turned the ق of بدقة into a hamza)."""
    words = _file()[2]
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


def _digits_en(m: re.Match) -> str:
    """The same choice as _digits, in words: an identifier digit by digit, anything else as a number."""
    spaced = _digits(m)
    if " " in spaced:
        return re.sub(r"\d", lambda d: EN_ONES[int(d.group(0))], spaced)
    whole, _, fraction = spaced.partition(".")
    if not whole.isdigit() or (fraction and not fraction.isdigit()):
        return spaced
    return english_number(int(whole)) + (" point " + " ".join(EN_ONES[int(d)] for d in fraction) if fraction else "")


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
    if lang == "en":                                                    # EGP 20,000 is said "twenty thousand Egyptian pounds"
        text = re.sub(r"\b(EGP|USD|EUR|SAR)\s*(\d[\d,.]*\d|\d)", r"\2 \1", text)
    for pattern, spoken in _file()[0].get(lang, []):                 # before the amounts: EGP becomes جنيه first
        text = pattern.sub(spoken, text)
    if lang == "en":
        text = NUMBER.sub(_digits_en, ORDINAL.sub(_ordinal_en, text)).replace("%", " percent")
    else:
        text = HUNDRED_OF.sub(lambda m: egyptian_number(int(m.group(1)), counting=True) + " ", FRACTION.sub(_fraction, MONEY.sub(_money, text)))
        text = PERCENT.sub(" في المية", NUMBER.sub(_digits, text))
    return re.sub(r"[ \t]+", " ", text).strip()
