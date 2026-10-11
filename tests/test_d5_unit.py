"""D5 unit tests that need no model: template matching by article number, quote normalisation and the
ruling amount helpers. Run: pytest tests/test_d5_unit.py (needs nbe_core and services/d5_legal on the path)."""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("D5_SEED_DIR", str(ROOT / "data" / "seed" / "d5"))
sys.path[:0] = [str(ROOT / "packages" / "nbe_core"), str(ROOT / "services" / "d5_legal")]

from app import main  # noqa: E402
from nbe_core.trace import Trace  # noqa: E402

SEED = Path(os.environ["D5_SEED_DIR"])

# D5 makes its structured calls through llm.chat(json_schema=...) and parses/repairs them itself. Tests
# describe the model as a fake llm.chat_json (dict out, or JSONOutputError with the raw text); this adapter
# turns that into what llm.chat would return. Plain-text calls go to PLAIN["fn"] when a test sets it.
PLAIN = {"fn": None}


class _Txt:
    latency_ms, completion_tokens, prompt_tokens = 1, 1, 1
    alias = model = served_by = "fake"

    def __init__(self, text):
        self.text = text

    def meta(self):
        return {}


@pytest.fixture(autouse=True)
def _chat_adapter(monkeypatch):
    PLAIN["fn"] = None

    async def chat(messages, alias="workhorse", *a, json_schema=None, **kw):
        if json_schema is None:
            return await PLAIN["fn"](messages) if PLAIN["fn"] else _Txt("ملخص")
        try:
            d, _ = await main.llm.chat_json(messages, json_schema)
        except main.llm.JSONOutputError as exc:
            return _Txt(exc.raw)
        return _Txt(json.dumps(d, ensure_ascii=False))
    monkeypatch.setattr(main.llm, "chat", chat)


def _no_deviation(monkeypatch):
    async def fake_chat_json(messages, schema, *a, **kw):
        class R:
            latency_ms = 1
        return {"deviates": False, "severity": "none", "changes": [], "risk": ""}, R()
    monkeypatch.setattr(main.llm, "chat_json", fake_chat_json)


def test_c05_deleted_article_9_is_missing(monkeypatch):
    # C05 drops article 9 but keeps 10-12 numbered: matching is by number, so 9 must show as missing
    _no_deviation(monkeypatch)
    chunks = main.split_clauses((SEED / "C05.md").read_text(encoding="utf-8"))
    rows, flags = asyncio.run(main.template_diff(chunks, Trace()))
    row = next(r for r in rows if r["article"] == 9)
    assert row["status"] == "missing" and row["severity"] == "high"
    assert {r["article"] for r in rows if r["status"] == "same"} == set(range(1, 13)) - {9}
    assert flags[0]["article"] == 9


def test_malformed_json_marks_one_article_unchecked(monkeypatch):
    # Article 6 always yields malformed JSON: the document still completes, 6 is unchecked, not a deviation
    calls = []

    async def chat_json(messages, schema, *a, **kw):
        if "المادة 6 - التأخر في السداد" in messages[0]["content"]:
            calls.append(6)
            raise main.llm.JSONOutputError("Expecting ',' delimiter", '{"deviates": true "x"}')
        class R:
            latency_ms = 1
        return {"deviates": False, "severity": "none", "changes": [], "risk": ""}, R()
    monkeypatch.setattr(main.llm, "chat_json", chat_json)
    chunks = main.split_clauses((SEED / "C01.md").read_text(encoding="utf-8"))
    rows, flags = asyncio.run(main.template_diff(chunks, Trace()))
    row = next(r for r in rows if r["article"] == 6)
    assert row["status"] == "unchecked" and calls == [6, 6, 6, 6]      # 2 tries workhorse, 2 on the fallback
    assert flags == [] and main.compound_risks(rows, en=False) == []


def test_unusable_workhorse_verdict_is_retried_on_the_fallback_model(monkeypatch):
    aliases = []

    async def chat(messages, alias="workhorse", *a, json_schema=None, **kw):
        if "المادة 12 -" in messages[0]["content"]:
            aliases.append(alias)
            if alias == "workhorse":
                return _Txt('{"sever')                                   # unusable, verdict never written
            return _Txt('{"deviates": true, "severity": "high", "changes": [], "risk": "law"}')
        return _Txt('{"deviates": false, "severity": "none", "changes": [], "risk": ""}')
    monkeypatch.setattr(main.llm, "chat", chat)
    chunks = main.split_clauses((SEED / "C03.md").read_text(encoding="utf-8"))
    rows, _ = asyncio.run(main.template_diff(chunks, Trace()))
    row = next(r for r in rows if r["article"] == 12)
    assert row["status"] == "deviates" and row["severity"] == "high"
    assert aliases == ["workhorse", "workhorse", main.FALLBACK_ALIAS]


def test_repair_json_closes_truncated_output():
    # Real 31B output from OpenRouter: stopped after "changes": []
    raw = '{\n  "deviates": false,\n  "severity": "none",\n  "changes": [] '
    d = main.repair_json(raw, main.DIFF_SCHEMA)
    assert d["deviates"] is False and d["changes"] == [] and d["risk"] == "" and d["_filled"] == ["risk"]
    cut = main.repair_json('{"deviates": true, "severity": "hi', main.DIFF_SCHEMA)
    assert cut["severity"] == "hi" and "changes" in cut["_filled"]
    assert main.repair_json("not json at all", main.DIFF_SCHEMA) is None


def _raising_then(raw):
    async def chat_json(messages, schema, *a, **kw):
        raise main.llm.JSONOutputError("Expecting ',' delimiter", raw)
    return chat_json


def test_truncated_verdict_is_used_but_invented_one_is_not(monkeypatch):
    chunks = main.split_clauses((SEED / "E01.md").read_text(encoding="utf-8"))
    monkeypatch.setattr(main.llm, "chat_json", _raising_then('{"deviates": true, "severity": "high", "changes": ['))
    rows, flags = asyncio.run(main.template_diff(chunks, Trace(), en=True))
    assert all(r["status"] == "deviates" for r in rows if r["article"] != 9) and flags
    monkeypatch.setattr(main.llm, "chat_json", _raising_then('{"sever'))       # verdict never written
    rows, flags = asyncio.run(main.template_diff(chunks, Trace(), en=True))
    assert all(r["status"] == "unchecked" for r in rows) and flags == []


def test_unusable_reduce_output_falls_back_to_part_summaries(monkeypatch):
    async def chat(messages, *a, **kw):
        return _Res()
    PLAIN["fn"] = chat
    monkeypatch.setattr(main.llm, "chat_json", _raising_then("garbage"))
    r = asyncio.run(main.analyze_text("R01.md", (SEED / "R01.md").read_text(encoding="utf-8"), "ruling"))
    s = r["summary"]
    assert s["amounts"][0] == "47,300 جنيه مصري" and s["court"].startswith("المحكمة الاقتصادية بالقاهرة")
    assert s["key_points"] and "_filled" not in s


def test_empty_outcome_comes_from_operative_part(monkeypatch):
    # Seen with the 26B: outcome and outcome_or_obligations both empty for R01
    _fake_llm(monkeypatch, {**SUMMARY, "outcome": "", "outcome_or_obligations": "", "amounts": ["47,300"]}, [])
    r = asyncio.run(main.analyze_text("R01.md", (SEED / "R01.md").read_text(encoding="utf-8"), "ruling"))
    assert r["summary"]["outcome"].startswith("بقبول الدعوى جزئياً")


def test_gateway_timeout_marks_article_unchecked(monkeypatch):
    # Seen on OpenRouter: a hung request timed out and failed the whole E01 document
    async def chat_json(messages, schema, *a, **kw):
        if "Article 6 - Late Payment" in messages[0]["content"]:
            raise main.httpx.ReadTimeout("timed out")
        class R:
            latency_ms = 1
        return {"deviates": False, "severity": "none", "changes": [], "risk": ""}, R()
    monkeypatch.setattr(main.llm, "chat_json", chat_json)
    chunks = main.split_clauses((SEED / "E01.md").read_text(encoding="utf-8"))
    rows, _ = asyncio.run(main.template_diff(chunks, Trace(), en=True))
    assert next(r for r in rows if r["article"] == 6)["status"] == "unchecked"
    assert all(r["status"] == "same" for r in rows if r["article"] != 6)


def test_map_timeout_uses_part_text_and_document_completes(monkeypatch):
    _fake_llm(monkeypatch, SUMMARY, [])

    async def chat(messages, *a, **kw):
        if "المادة 6" in messages[0]["content"]:
            raise main.httpx.ConnectTimeout("timed out")
        return _Res()
    PLAIN["fn"] = chat
    r = asyncio.run(main.analyze_text("C01.md", (SEED / "C01.md").read_text(encoding="utf-8"), "contract"))
    assert r["summary"]["key_points"] and r["diff"]


def test_insurance_liability_data_capped_at_medium(monkeypatch):
    async def chat_json(messages, schema, *a, **kw):
        class R:
            latency_ms = 1
        return {"deviates": True, "severity": "high", "changes": [], "risk": "x"}, R()
    monkeypatch.setattr(main.llm, "chat_json", chat_json)
    # E01 is English, so every article goes to the (fake) model, which calls everything high
    chunks = [c for c in main.split_clauses((SEED / "E01.md").read_text(encoding="utf-8")) if c["no"] != 9]
    rows, _ = asyncio.run(main.template_diff(chunks, Trace(), en=True))
    sev = {r["article"]: r["severity"] for r in rows}
    assert sev[7] == sev[10] == sev[11] == "medium"
    assert sev[9] == "high" and sev[6] == sev[3] == "high"     # deleted article / other articles untouched


def test_quote_normalisation_ignores_diacritics_and_letter_forms():
    doc = main._norm_quote("يكون التأمين على الحياة إلزامي طوال مدة التمويل")
    assert main._norm_quote("«يكونُ التامين علي الحياه الزامي.»") in doc
    assert main._norm_quote("التأمين اختياري") not in doc


def test_r02_awarded_amounts_lead_and_unsupported_amounts_flagged():
    text = (SEED / "R02.md").read_text(encoding="utf-8")
    operative = main._operative_part(main.split_clauses(text))
    assert "72,000" in operative
    ordered = main._order_amounts(["120,000 جنيه", "72,000 جنيه", "48,000 جنيه"], operative)
    assert ordered[:2] == ["72,000 جنيه", "48,000 جنيه"]
    assert main._unsupported_amounts(ordered, text, en=False) == []
    flags = main._unsupported_amounts(["99,999 جنيه"], text, en=False)
    assert len(flags) == 1 and flags[0]["changes"][0]["contract"] == "99,999 جنيه"


class _Res:
    text, latency_ms, completion_tokens, prompt_tokens = "ملخص", 1, 1, 1
    alias = model = served_by = "fake"

    def meta(self):
        return {}


def _fake_llm(monkeypatch, summary: dict, prompts: list):
    async def chat(messages, *a, **kw):
        prompts.append(messages[0]["content"])
        return _Res()

    async def chat_json(messages, schema, *a, **kw):
        prompts.append(messages[0]["content"])
        if schema is main.SUMMARY_SCHEMA:
            return dict(summary), _Res()
        if schema is main.CLAUSE_SCHEMA:
            return {"clauses": []}, _Res()
        if "المادة 6 - التأخر في السداد" in messages[0]["content"]:      # C01's planted deviation
            return {"deviates": True, "severity": "high", "changes": [], "risk": "x"}, _Res()
        return {"deviates": False, "severity": "none", "changes": [], "risk": ""}, _Res()
    PLAIN["fn"] = chat
    monkeypatch.setattr(main.llm, "chat_json", chat_json)


SUMMARY = {"document_type": "x", "parties": [], "outcome_or_obligations": "x", "amounts": [],
           "key_points": ["[م.6] تقصير مهلة التأخر", "[م.6] حذف الإنذار", "[م.3] عائد متغير"],
           "court": "should be dropped for contracts",
           "compound_risks": [{"articles": [6, 9], "severity": "high", "risk": "مهلة أقصر بلا إنذار"}]}


def test_contract_summary_fields_and_timestamp(monkeypatch):
    _fake_llm(monkeypatch, SUMMARY, prompts := [])
    r = asyncio.run(main.analyze_text("C01.md", (SEED / "C01.md").read_text(encoding="utf-8"), "contract"))
    s = r["summary"]
    assert s["article_refs"] == [6, 3]
    assert s["court"] is None and s["outcome"] is None and s["award_split"] is None
    assert r["analyzed_at"].endswith("+00:00")
    assert "compound_risks" not in main.SUMMARY_SCHEMA["properties"]      # the model is not asked for it
    diff_prompts = [p for p in prompts if "النموذج المعتمد:" in p]
    assert diff_prompts and all(main.SEVERITY_RUBRIC in p for p in diff_prompts)


def test_compound_risk_among_unchanged_articles_is_dropped(monkeypatch):
    noise = {**SUMMARY, "compound_risks": [{"articles": [4, 5], "severity": "medium", "risk": "x"}]}
    _fake_llm(monkeypatch, noise, [])
    r = asyncio.run(main.analyze_text("C01.md", (SEED / "C01.md").read_text(encoding="utf-8"), "contract"))
    assert not [f for f in r["risk_flags"] if f.get("compound")] and r["summary"]["compound_risks"] == []


def test_c01_compound_risk_is_deterministic(monkeypatch):
    # Whatever the model says about compound risks, C01's result comes from which articles deviate
    text = (SEED / "C01.md").read_text(encoding="utf-8")
    runs = []
    for junk in ([], [{"articles": [5, 6], "severity": "high", "risk": "a"}], [{"articles": [6, 9], "severity": "low", "risk": "b"}]):
        _fake_llm(monkeypatch, {**SUMMARY, "compound_risks": junk}, [])
        r = asyncio.run(main.analyze_text("C01.md", text, "contract"))
        runs.append((r["summary"]["compound_risks"], [f for f in r["risk_flags"] if f.get("compound")]))
    assert runs[0] == runs[1] == runs[2]
    assert runs[0] == ([], [])          # only article 6 deviates in C01: no theme has two deviating articles


def _row(article, severity, risk="r"):
    return {"article": article, "title": f"t{article}", "status": "deviates", "severity": severity, "risk": risk}


def test_compound_risk_fires_on_two_deviating_articles_of_one_theme():
    diff = [_row(6, "high", "cure period"), _row(9, "medium", "termination"), _row(11, "medium"),
            {"article": 5, "title": "t5", "status": "same", "severity": "none", "risk": ""}]
    out = main.compound_risks(diff, en=False)
    assert [(c["theme"], c["articles"], c["severity"]) for c in out] == [("default_and_exit", [6, 9], "high")]
    assert main.compound_risks(diff, en=False) == out
    flags = main._compound_flags(out, en=False)
    assert flags[0]["compound"] and flags[0]["articles"] == [6, 9] and flags[0]["article"] == 6
    both = main.compound_risks([_row(3, "high"), _row(5, "medium"), _row(6, "medium")], en=True)
    assert [(c["theme"], c["articles"]) for c in both] == [("cost_of_credit", [3, 5, 6])]


def test_r01_amount_carries_source_currency(monkeypatch):
    text = (SEED / "R01.md").read_text(encoding="utf-8")
    units = main._source_units(text)
    assert units["47300"] == "جنيه مصري"
    assert main._with_unit("47,300", units) == main._with_unit("47,300 جنيه", units) == "47,300 جنيه مصري"
    _fake_llm(monkeypatch, {**SUMMARY, "amounts": ["47,300", "47,300 جنيه"]}, [])
    r = asyncio.run(main.analyze_text("R01.md", text, "ruling"))
    assert r["summary"]["amounts"] == ["47,300 جنيه مصري"]


def test_court_is_read_from_the_header():
    for f, court in (("R01.md", "المحكمة الاقتصادية بالقاهرة"), ("R03.md", "المحكمة الاقتصادية بالإسكندرية")):
        assert main._court_from_header((SEED / f).read_text(encoding="utf-8")).startswith(court)


def test_empty_ruling_summary_falls_back_to_operative_part(monkeypatch):
    # Seen with the 26B: amounts, court and outcome all empty for R01
    empty = {**SUMMARY, "amounts": [], "court": "", "outcome": "", "outcome_or_obligations": "رد الفرق"}
    _fake_llm(monkeypatch, empty, [])
    r = asyncio.run(main.analyze_text("R01.md", (SEED / "R01.md").read_text(encoding="utf-8"), "ruling"))
    s = r["summary"]
    assert s["amounts"][0] == "47,300 جنيه مصري"
    assert s["court"].startswith("المحكمة الاقتصادية بالقاهرة") and s["outcome"] == "رد الفرق"


def test_award_split_keeps_operative_amounts_payers_first():
    text = (SEED / "R02.md").read_text(encoding="utf-8")
    op = main._operative_part(main.split_clauses(text))
    units = main._source_units(text)
    split = [{"party": "أحمد محمود علي", "role": "bears_loss", "amount": "48,000", "share": "40%"},
             {"party": "بنك النيل", "role": "pays", "beneficiary": "أحمد محمود علي", "amount": "72,000", "share": "60%"},
             {"party": "x", "role": "pays", "amount": "999", "share": "1%"}]
    out = main._check_split(split, op, units)
    assert [(s["party"], s["amount"]) for s in out] == [("بنك النيل", "72,000 جنيه مصري"), ("أحمد محمود علي", "48,000 جنيه مصري")]
    assert main._check_split([], op, units) is None


def test_english_amount_keeps_egp_prefix():
    units = main._source_units((SEED / "E01.md").read_text(encoding="utf-8"))
    assert main._with_unit("2,500,000", units) == "EGP 2,500,000"


def test_amounts_without_numbers_are_dropped(monkeypatch):
    _fake_llm(monkeypatch, {**SUMMARY, "amounts": ["غير متوفر", "47,300 جنيه", "47,300 جنيه"]}, [])
    r = asyncio.run(main.analyze_text("R01.md", (SEED / "R01.md").read_text(encoding="utf-8"), "ruling"))
    assert r["summary"]["amounts"] == ["47,300 جنيه مصري"] and r["summary"]["compound_risks"] == []


def test_english_contract_routes_to_english_output(monkeypatch):
    text = (SEED / "E01.md").read_text(encoding="utf-8")
    assert main.is_english(text) and not main.is_english((SEED / "C01.md").read_text(encoding="utf-8"))
    assert [c["no"] for c in main.split_clauses(text)] == list(range(1, 13))
    _fake_llm(monkeypatch, {**SUMMARY, "key_points": ["[Art.6] shorter cure period"]}, prompts := [])
    r = asyncio.run(main.analyze_text("E01.md", text, "contract"))
    diff = [p for p in prompts if p.startswith("Compare the article")]
    assert diff and all(main.SEVERITY_RUBRIC_EN in p and "Answer in English" in p for p in diff)
    assert all("باللغة الإنجليزية" in p for p in prompts if p not in diff)
    assert r["summary"]["article_refs"] == [6]


def test_manifest_lists_e01_with_c01_deviation():
    import json
    m = json.loads((SEED / "manifest.json").read_text(encoding="utf-8"))
    e01 = next(c for c in m["contracts"] if c["file"] == "E01.md")
    assert e01["lang"] == "en" and [d["title"] for d in e01["deviations"]] == ["التأخر في السداد"]


def test_numbers_handle_arabic_indic_digits():
    assert main._numbers("٧٢٬٠٠٠ جنيه") == main._numbers("72,000 جنيه") == ["72000"]
