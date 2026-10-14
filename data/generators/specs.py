"""Fact sheets for every authored corpus, for the active country (COUNTRY in .env: EG, SA, AE, MA).

Each country is one module in data/generators/countries/ with the same names and shapes. The LLM writes prose
around these facts; it never chooses them, so the golden answers for D2/D5/D7 are correct by construction.

The corpus in data/seed/<CC> carries one bank's name (data/seed/<CC>/bank.json); scripts/apply_customer.py swaps it
for the active customer's. So whatever is written into it again (d5_clauses, a partial re-author) uses that same
name, never the active customer's, and the corpus stays consistent.
"""
import importlib
import json
import os
from pathlib import Path

from nbe_core import locale as L

_bank = Path(__file__).resolve().parent.parent / "seed" / L.CODE / "bank.json"
AUTHORED_FOR = (json.loads(_bank.read_text(encoding="utf-8")) if _bank.exists() else
                {"ar": os.getenv("BANK_NAME_AR", ""), "en": os.getenv("BANK_NAME_EN", ""), "short": os.getenv("BANK_SHORT", "")})
os.environ["BANK_NAME_AR"] = AUTHORED_FOR["ar"] or os.getenv("BANK_NAME_AR", "")   # read by the country module below

_pack = importlib.import_module(f"data.generators.countries.{L.CODE.lower()}")
globals().update({k: v for k, v in vars(_pack).items() if not k.startswith("__")})
