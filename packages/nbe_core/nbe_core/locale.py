"""Locale pack: everything country-specific that the services and data generators use.

The country comes from COUNTRY in .env (EG, SA, AE, MA), set by `make customer NAME=<customer>` from the
customer's profile (customers/<name>/customer.json). Each country is one module in nbe_core/countries/ with the same
names and shapes; only the values change. All lists are synthetic (fictitious people, companies and merchants).

What belongs to the bank rather than the country (its own contact facts for D6 drafting) comes from the active
customer profile, written to /data/customer.json by scripts/apply_customer.py.
"""
import importlib
import json
import os
from pathlib import Path

CODE = os.getenv("COUNTRY", "EG").strip().upper() or "EG"
_pack = importlib.import_module(f"nbe_core.countries.{CODE.lower()}")
globals().update({k: v for k, v in vars(_pack).items() if not k.startswith("__")})

# The active customer (written by scripts/apply_customer.py); absent on an old checkout, then the country's defaults hold
_CUSTOMER_FILE = Path(os.getenv("CUSTOMER_FILE", "/data/customer.json"))
try:
    CUSTOMER = json.loads(_CUSTOMER_FILE.read_text(encoding="utf-8"))
except (OSError, ValueError):
    CUSTOMER = {}

# D6 drafting: what a letter may state about the bank without being told: (label, value)
if CUSTOMER.get("facts"):
    BANK_FACTS = [(f["label"], f["value"]) for f in CUSTOMER["facts"]]
else:
    BANK_FACTS = list(getattr(_pack, "BANK_FACTS", []))

# D6 translation: the bank's own name is always one of its terms
_names = CUSTOMER.get("name") or {}
if _names.get("ar") and _names.get("en"):
    GLOSSARY = [(_names["ar"], _names["en"])] + [g for g in getattr(_pack, "GLOSSARY", []) if g[0] != _names["ar"]]


def li(name: str) -> str:
    """«لـ» before a name, joined the Arabic way: البنك الأهلي -> للبنك الأهلي, بنك الرياض -> لبنك الرياض."""
    return "ل" + name[1:] if name.startswith("ال") else "ل" + name
