"""D3 unit tests that need no model or database: the compliance rules (the demo's live safety moment), the
code-side enforcement that runs when the model cannot fix the copy, and SMS part counting.
Run: pytest tests/test_d3_unit.py (needs nbe_core and services/d3_campaigns on the path)."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "nbe_core"))
# Loaded under its own name: every service package is called "app", so "from app import main" would clash with D5's tests.
_spec = importlib.util.spec_from_file_location("d3_main", ROOT / "services" / "d3_campaigns" / "app" / "main.py")
main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(main)
from nbe_core.text import normalize_map  # noqa: E402

AR_OK = "استرداد نقدي 15% بحد أقصى 250 جنيه في مطعم النخيل حتى 30 نوفمبر. تطبق الشروط والأحكام"
EN_OK = "15% cashback up to EGP 250 at Al Nakheel until 30 Nov. T&Cs apply"


def rules(text: str) -> set[str]:
    return {i["rule"] for i in main.compliance({"sms_a_ar": text})}


def banned(text: str) -> list[str]:
    return [label for label, _, _ in main.banned_spans(text)]


def test_normalize_map_points_back_to_original():
    text = "عائـــد مَضْمُون ١٠٠٪"
    norm, idx = normalize_map(text)
    assert norm == "عايد مضمون 100%"   # ئ folds to ي
    assert len(idx) == len(norm) and text[idx[norm.index("100")]] == "١" and text[idx[-1]] == "٪"


@pytest.mark.parametrize("text", [
    "عائد مضمون 100%", "عائد مضمون 100 %", "عائد ١٠٠٪", "عائد ١٠٠ ٪", "ربح ۱۰۰٪", "عائد 100 في المية", "عائد مية في المية",
    "مكسب مضمونة", "مكاسب مضمونه", "الربح المضمون", "وبالمضمون", "مضـــمون", "مَضْمُون", "مض‌مون", "نضمن لك أعلى عائد",
    "إحنا بنضمنلك", "إحنا بنضمن لك",
    "أفضل من أي بنك", "افضل بنك في مصر", "البنك الأفضل", "مجاناً تماماً", "مجانا تماما", "بدون أي شروط", "بدون شروط",
    "من غير أي شروط", "بلا مخاطر", "Guaranteed returns", "GUARANTEE", "risk-free", "risk free", "the best bank", "no strings attached",
])
def test_banned_claims_caught(text):
    assert banned(text), text


@pytest.mark.parametrize("text", [
    AR_OK, EN_OK, "خصم 10% على مشترياتك", "أفضل العروض لك هذا الشهر", "مضمار الجري", "ضمان المنتج من التاجر", "العرض يتضمن خصماً", "الباقة تتضمن",
    "استرداد 1000 جنيه", "استرداد 2100% ", "استرداد نقدي 100 جنيه",
])
def test_clean_text_not_flagged(text):
    assert banned(text) == [], text


@pytest.mark.parametrize("text", [
    "خصم 15% تطبق الشروط والأحكام", "خصم 15% تطبق الشروط و الأحكام", "خصم 15% تُطبَّق الشروط والأحكام", "خصم 15% تطبق الشروط واﻷحكام".replace("ﻷ", "لأ"),
    "خصم 15% تنطبق الشروط والاحكام", "خصم 15% تطبق   الشروط\nوالأحكام", "خصم 15% تطبّق الشروط والأحكام.",
])
def test_disclaimer_variants_accepted(text):
    assert "required_disclaimer" not in rules(text), text


def test_disclaimer_missing_and_english_variants():
    assert "required_disclaimer" in rules("خصم 15% على مشترياتك")
    ok = lambda t: not [i for i in main.compliance({"sms_en": t}) if i["rule"] == "required_disclaimer"]
    assert ok("Cashback. T&Cs apply.") and ok("Cashback. T & C apply") and ok("Cashback. Terms and conditions apply")
    assert not ok("Cashback for you")


def test_sms_parts():
    assert main.sms_parts("a" * 160)[1:] == (1, "GSM-7")
    assert main.sms_parts("a" * 161)[1] == 2
    assert main.sms_parts("ب" * 70)[1:] == (1, "UCS-2")
    assert main.sms_parts("ب" * 71)[1] == 2
    assert main.sms_parts("ب" * 134)[1] == 2 and main.sms_parts("ب" * 135)[1] == 3
    assert main.sms_parts("Café é")[2] == "GSM-7" and main.sms_parts("price ≤ 5")[2] == "UCS-2"


def test_sms_info_reports_the_limit_for_its_language_and_encoding():
    ar = main.sms_info("sms_a_ar", "ب" * 115)
    assert (ar["chars"], ar["parts"], ar["encoding"], ar["max_parts"], ar["max_chars"]) == (115, 2, "UCS-2", 2, 134)
    en = main.sms_info("sms_en", "a" * 100)
    assert (en["parts"], en["encoding"], en["max_parts"], en["max_chars"]) == (1, "GSM-7", 1, 160)
    assert main.sms_info("sms_en", "price ≤ 5")["max_chars"] == 70     # one part, but UCS-2 because of "≤"


def test_arabic_sms_limit_is_two_parts_not_160_chars():
    assert "sms_length" in rules(("خصم " * 40) + "تطبق الشروط والأحكام")   # ~180 chars UCS-2 = 3 parts
    assert "sms_length" not in rules(AR_OK)


def test_enforce_removes_claim_keeps_offer_and_disclaimer():
    bad = {"sms_a_ar": "عائد مضمون ١٠٠٪، استرداد نقدي 15% بحد أقصى 250 جنيه. تطبق الشروط والأحكام",
           "sms_en": "Guaranteed 100% returns! 15% cashback up to EGP 250"}
    fixed, actions = main.enforce(bad)
    assert main.compliance(fixed) == []
    assert "15%" in fixed["sms_a_ar"] and "250" in fixed["sms_a_ar"] and fixed["sms_a_ar"].endswith("تطبق الشروط والأحكام")
    assert "15% cashback" in fixed["sms_en"] and fixed["sms_en"].endswith("T&Cs apply")
    assert {a["action"] for a in actions} == {"removed_claim", "added_disclaimer"}


def test_enforce_claim_in_disclaimer_clause_cuts_only_the_claim():
    fixed, _ = main.enforce({"sms_a_ar": "استرداد 15% مضمون تطبق الشروط والأحكام"})
    assert main.compliance(fixed) == [] and "15%" in fixed["sms_a_ar"]


def test_enforce_trims_long_sms_keeping_disclaimer():
    fixed, actions = main.enforce({"sms_a_ar": ("استرداد نقدي " * 20) + "تطبق الشروط والأحكام"})
    assert main.compliance(fixed) == [] and fixed["sms_a_ar"].endswith("تطبق الشروط والأحكام")
    assert actions[-1]["action"] == "trimmed_sms"


def test_stress_test_phrase_always_ends_clean():
    copy = {k: AR_OK for k in ("sms_a_ar", "sms_b_ar", "email_body_ar", "social_egy")} | {k: EN_OK for k in ("sms_en", "email_body_en")}
    copy |= {"email_subject_ar": "عرض", "email_subject_en": "Offer", "banner_headline_ar": "استرداد نقدي الآن"}
    copy["sms_a_ar"] = "عائد مضمون 100%! " + AR_OK
    assert {i["rule"] for i in main.compliance(copy)} == {"banned_claim"}
    fixed, _ = main.enforce(copy)
    assert main.compliance(fixed) == [] and fixed["sms_b_ar"] == AR_OK


OFFER = {"merchant": "مطعم أبو شقرة التجريبي", "cashback_pct": 15, "cap_egp": 250, "valid_until": "2026-11-30"}


def test_disclaimer_only_message_fails_offer_terms():
    issues = main.compliance({"sms_a_ar": "تطبق الشروط والأحكام", "sms_en": "T&Cs apply"}, OFFER)
    assert {(i["field"], i["rule"]) for i in issues} == {("sms_a_ar", "offer_terms"), ("sms_en", "offer_terms")}


@pytest.mark.parametrize("text", [
    "استرداد ١٥٪ حتى ٢٥٠ جنيه في مطعم أبو شقرة. تطبق الشروط والأحكام", "استرداد 15 % بحد أقصى 250 من أبو شقرة تطبق الشروط والأحكام",
])
def test_offer_terms_accepted(text):
    assert main.compliance({"sms_a_ar": text}, OFFER) == []


def test_wrong_rate_is_caught_and_replaced():
    copy = {"sms_a_ar": "استرداد 20% حتى 250 جنيه في مطعم أبو شقرة. تطبق الشروط والأحكام"}
    assert main.compliance(copy, OFFER)[0]["detail"] == "missing 15%"
    fixed, actions = main.enforce(copy, OFFER)
    assert main.compliance(fixed, OFFER) == [] and actions[0]["action"] == "replaced_with_offer_terms"


def test_offer_text_is_itself_compliant():
    for key in main.FACT_FIELDS:
        for o in (OFFER, {**OFFER, "merchant": "منتجع العين السخنة التجريبي", "cashback_pct": 12, "cap_egp": 2500}):
            assert main.compliance({key: main.offer_text(key, o)}, o) == [], (key, o["merchant"])
