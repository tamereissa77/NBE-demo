"""Every country pack is complete and consistent (no model, database or network needed):
    docker run --rm -v .:/repo:ro -w /repo nbe-datagen python tests/test_countries.py

- nbe_core/countries/<cc>.py and data/generators/countries/<cc>.py define the same names as Egypt's
- the D4 dialect block, the portal locale and the ID rules have every key the services read
- the currency patterns match the amounts as the corpus writes them
- a masked ID from the D1 generator passes that country's own ID check, and ends in its last 4 digits
- every D5 contract fact appears verbatim in its article text (d5_clauses.check)
- D2_SUGGESTED's "dia" question exists, and the customer profiles in customers/ name a known country
"""
import ast
import importlib
import json
import os
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "packages" / "nbe_core")]
LOCALES = ROOT / "packages" / "nbe_core" / "nbe_core" / "countries"
SPECS = ROOT / "data" / "generators" / "countries"
CODES = sorted(p.stem.upper() for p in LOCALES.glob("[a-z][a-z].py"))
D4_KEYS = {"dialect", "speaker", "words", "openers", "formal", "greet", "greet_re", "filler_re", "honorific_re", "promise_re",
           "compliment", "smalltalk", "ask_code", "done", "unclear", "refusal"}
SMALLTALK = {"thanks", "age", "where", "who", "other"}
PORTAL_KEYS = {"country", "currency", "nationalId", "dialect", "d4Script"}

passed = failed = 0


def check(ok: bool, what: str) -> None:
    global passed, failed
    passed, failed = passed + bool(ok), failed + (not ok)
    print(("  PASS " if ok else "  FAIL ") + what)


def names(path: Path) -> set[str]:
    out = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        for t in targets:
            out |= {t.id} if isinstance(t, ast.Name) else {e.id for e in getattr(t, "elts", []) if isinstance(e, ast.Name)}
        if isinstance(node, ast.FunctionDef):
            out.add(node.name)
    return out


def load(code: str):
    """The country's locale and specs modules, as the services and generators see them with COUNTRY=<code>."""
    os.environ["COUNTRY"], os.environ["CUSTOMER_FILE"] = code, "/nonexistent"
    for mod in [m for m in sys.modules if m.startswith(("nbe_core.locale", "nbe_core.countries", "data.generators"))]:
        del sys.modules[mod]
    return importlib.import_module("nbe_core.locale"), importlib.import_module("data.generators.specs")


base_locale, base_specs = names(LOCALES / "eg.py"), names(SPECS / "eg.py")
print(f"countries: {', '.join(CODES)}")
for code in CODES:
    print(f"\n{code}")
    cc = code.lower()
    check(names(LOCALES / f"{cc}.py") == base_locale, f"locale defines the same names as Egypt's "
          f"(missing {sorted(base_locale - names(LOCALES / f'{cc}.py'))}, extra {sorted(names(LOCALES / f'{cc}.py') - base_locale)})")
    check((SPECS / f"{cc}.py").exists() and names(SPECS / f"{cc}.py") - {"RULING_NOUN"} == base_specs - {"RULING_NOUN"},
          "fact sheets define the same names as Egypt's")
    L, specs = load(code)
    check(L.CODE == code and L.COUNTRY == code, "the loader picks this country")
    check(set(L.D4) == D4_KEYS and set(L.D4["smalltalk"]) == SMALLTALK, "D4 dialect block has every key")
    check(all("{li_bank_ar}" in L.D4["smalltalk"][k] for k in ("where", "who", "other")), "D4 small talk names the bank")
    for key in ("greet_re", "filler_re", "honorific_re", "promise_re"):
        try:
            re.compile(L.D4[key])
            ok = True
        except re.error:
            ok = False
        check(ok, f"D4 {key} is a valid pattern")
    check(set(L.PORTAL) == PORTAL_KEYS and len(L.PORTAL["d4Script"]["ar"]) == len(L.PORTAL["d4Script"]["en"]) == 6
          and "{code}" in L.PORTAL["d4Script"]["ar"], "portal locale is complete (6 scripted D4 turns each way)")
    check(set(L.NATIONAL_ID) == {"length", "prefixes", "decode"}, "ID rules have length, prefixes and decode")
    unit = re.compile(rf"\d[\d,]*\s*(?:{L.CURRENCY_FORMS_AR})")
    amounts = [c["amount"] for c in specs.CONTRACTS] + [r["amount"] for r in specs.RULINGS if r["amount"] != "—"]
    check(all(unit.search(a) for a in amounts), f"every D5 amount is written with the local currency ({L.CURRENCY_AR})")
    check(L.CURRENCY_LONG_AR.startswith(L.CURRENCY_AR) and L.CURRENCY_EN_LONG.endswith("s"), "currency names fit D5's unit pattern")
    rng = random.Random(7)
    for _ in range(20):
        last4 = f"{rng.randint(0, 9999):04d}"
        masked = L.d1_nid_masked(rng, last4)
        if not masked.endswith(last4):
            break
    check(masked.endswith(last4), "a masked ID ends in its last 4 digits (D1 compares them with the HR letter)")
    spec_len, prefixes = L.NATIONAL_ID["length"], L.NATIONAL_ID["prefixes"]
    sample = "".join(c for c in masked.replace("X", "0") if c.isdigit())
    check((not spec_len or len(sample) == spec_len) and (not prefixes or sample.startswith(tuple(prefixes))),
          f"a masked ID has the country's length and prefix ({masked})")
    sys.modules.pop("data.generators.d5_clauses", None)
    d5 = importlib.import_module("data.generators.d5_clauses")
    problems = d5.check()
    check(not problems, "every D5 contract fact is in its article text" + (f": {problems[:3]}" if problems else ""))
    keys = {c["key"] for c in specs.TEMPLATE_CLAUSES}
    check(all(d["clause"] in keys for k in specs.CONTRACTS for d in k["deviations"]) and set(specs.CLAUSE_TEXT) == keys,
          "deviations and article texts cover the template's clauses")
    check(any(q["lang"] == "dia" for q in L.D2_SUGGESTED), "D2 offers a question in the local dialect")
    check(L.TZ.count("/") == 1 and len(L.WEEKEND) == 2, f"time zone and weekend set ({L.TZ})")

print("\ncustomers")
for profile in sorted((ROOT / "customers").glob("*/customer.json")):
    c = json.loads(profile.read_text(encoding="utf-8"))
    check(c.get("country", "").upper() in CODES and c.get("name", {}).get("ar") and c.get("name", {}).get("en") and c.get("short"),
          f"{profile.parent.name}: names and a known country ({c.get('country')})")

print(f"\ncountries: {passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
