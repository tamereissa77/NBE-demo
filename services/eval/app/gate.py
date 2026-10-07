"""Week-1 Arabic gate runner (PLAN.md §5).

    python -m app.gate run   --models workhorse,quality     # generate answers for every item
    python -m app.gate judge --judge hero                     # pre-score all answers with an LLM judge
    python -m app.gate summary                                # print the comparison table

Answers are generated at temperature 0 through the LiteLLM gateway, so each model is addressed by
its alias and the run records which model actually answered (a fallback would be visible).
"""
import argparse
import asyncio
import json
import os
import re
import uuid
from pathlib import Path

import yaml

from nbe_core import llm
from app import db
from app.tools import openai_tools

PROMPTS = Path(os.getenv("EVAL_PROMPTS", "/eval/prompts.yaml"))   # eval/arabic_gate, mounted read-only
GEN_MAX_TOKENS = 900


def load() -> dict:
    data = yaml.safe_load(PROMPTS.read_text(encoding="utf-8"))
    assert len(data["items"]) == 30, f"expected 30 items, found {len(data['items'])}"
    return data


def build_messages(item: dict, data: dict) -> tuple[list[dict], list[dict] | None]:
    msgs: list[dict] = []
    tools = None
    if ts := item.get("tool_set"):
        tool_set = data["tool_sets"][ts]
        msgs.append({"role": "system", "content": tool_set["system"].strip()})
        if not item.get("no_tools"):
            tools = openai_tools(tool_set["tools"])
    user = item["prompt"].strip()
    if ctx := item.get("context"):
        sources = "\n\n".join(data["contexts"][c].strip() for c in ctx)
        user = f"المصادر:\n{sources}\n\n---\n{user}"
    msgs.append({"role": "user", "content": user})
    return msgs, tools


def _parse_json(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else None


def auto_check(item: dict, text: str, tool_calls: list[dict]) -> tuple[bool | None, str]:
    check = item.get("check")
    if not check:
        return None, ""
    kind = check["type"]
    if kind == "tool":
        if not tool_calls:
            return False, "no tool call"
        first = tool_calls[0]["function"]["name"]
        return first == check["name"], f"first tool call: {first}"
    if kind == "json":
        try:
            obj = _parse_json(text)
        except json.JSONDecodeError:
            obj = None
        if not isinstance(obj, dict):
            return False, "not valid JSON"
        wrong = {k: obj.get(k) for k, v in check["fields"].items() if str(obj.get(k)).lower() != str(v).lower()}
        return not wrong, f"mismatched: {wrong}" if wrong else "all fields match"
    if kind in ("contains", "refuses"):
        hit = next((s for s in check["any"] if s.lower() in text.lower()), None)
        return hit is not None, f"found '{hit}'" if hit else "expected phrase missing"
    return None, f"unknown check {kind}"


async def run(aliases: list[str], only: set[str] | None = None) -> None:
    data = load()
    db.init()
    for alias in aliases:
        print(f"\n== {alias}", flush=True)
        for item in data["items"]:
            if only and item["id"] not in only:
                continue
            msgs, tools = build_messages(item, data)
            extra = {"reasoning_effort": "low"} if alias == "hero" else {}
            try:
                res = await llm.chat(msgs, alias, tools=tools, max_tokens=GEN_MAX_TOKENS, temperature=0, **extra)
            except Exception as exc:  # noqa: BLE001 - record the failure, keep going
                print(f"  {item['id']}: ERROR {type(exc).__name__}: {exc}", flush=True)
                continue
            ok, detail = auto_check(item, res.text, res.tool_calls)
            with db.connect() as conn:
                conn.execute(
                    """INSERT INTO eval.outputs (id, item_id, alias, model, text, tool_calls, latency_ms,
                           completion_tokens, tokens_per_s, auto_pass, auto_detail, judge)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL)
                       ON CONFLICT (item_id, alias) DO UPDATE SET model=EXCLUDED.model, text=EXCLUDED.text,
                           tool_calls=EXCLUDED.tool_calls, latency_ms=EXCLUDED.latency_ms,
                           completion_tokens=EXCLUDED.completion_tokens, tokens_per_s=EXCLUDED.tokens_per_s,
                           auto_pass=EXCLUDED.auto_pass, auto_detail=EXCLUDED.auto_detail, judge=NULL""",
                    (uuid.uuid4().hex[:12], item["id"], alias, res.model, res.text, json.dumps(res.tool_calls),
                     res.latency_ms, res.completion_tokens, res.tokens_per_s, ok, detail))
            mark = "" if ok is None else (" PASS" if ok else " FAIL")
            print(f"  {item['id']:7} {res.latency_ms:6} ms {res.tokens_per_s:5.1f} tok/s{mark} {detail}", flush=True)


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "correctness": {"type": "integer", "minimum": 1, "maximum": 5},
        "arabic": {"type": "integer", "minimum": 1, "maximum": 5},
        "format": {"type": "integer", "minimum": 1, "maximum": 5},
        "rationale": {"type": "string"},
    },
    "required": ["correctness", "arabic", "format", "rationale"],
}

JUDGE_SYSTEM = """You are a strict bilingual (Arabic/English) evaluator for a bank's AI assistant pilot.
Score the ANSWER to the TASK on three 1-5 scales:
- correctness: facts, numbers and actions are right and grounded in the provided sources; nothing invented. 5 = fully correct, 1 = wrong or harmful.
- arabic: quality of the language: fluent, natural, correct Modern Standard Arabic or appropriate local dialect register; understood dialect input; English parts correct. 5 = native-quality.
- format: follows the format and constraints that THIS TASK states, and only those. Examples of constraints a task may state:
  a length limit, JSON output, a number of bullet points, citing sources, a required phrase, or (when tools are offered and
  an action is needed) calling the tool rather than only describing it. Never penalise for a constraint the task does not
  state; for example, do not expect JSON unless the task asks for JSON. Do lower the score for an unrequested preamble
  ("Here is a suggested reply"), several alternatives when one was asked for, or markdown in text meant to be sent to a
  customer. 5 = every stated constraint met and nothing unrequested added.
Use the REFERENCE NOTES as the description of a good answer. Write a one-sentence rationale in English."""


def _describe_answer(row: dict) -> str:
    calls = row["tool_calls"] or []
    if calls:
        return "TOOL CALLS: " + "; ".join(f"{c['function']['name']}({c['function']['arguments']})" for c in calls) + \
               (f"\nTEXT: {row['text']}" if row["text"] else "")
    return row["text"] or "(empty)"


async def judge(judge_alias: str, force: bool = False, only: set[str] | None = None) -> None:
    data = load()
    items = {i["id"]: i for i in data["items"]}
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM eval.outputs" + ("" if force else " WHERE judge IS NULL") +
                            " ORDER BY item_id, alias").fetchall()
    if only:
        rows = [r for r in rows if r["item_id"] in only]
    if force and rows:
        # Clear old scores first, so a failed call can never leave a stale score behind
        with db.connect() as conn:
            conn.execute("UPDATE eval.outputs SET judge=NULL WHERE id = ANY(%s)", ([r["id"] for r in rows],))
    print(f"judging {len(rows)} answers with {judge_alias}", flush=True)
    for row in rows:
        item = items[row["item_id"]]
        msgs, _ = build_messages(item, data)
        task = "\n\n".join(m["content"] for m in msgs)
        prompt = (f"TASK (as given to the assistant):\n{task}\n\nREFERENCE NOTES (what a good answer contains):\n{item['good']}"
                  f"\n\nANSWER:\n{_describe_answer(row)}")
        scores = None
        # Malformed JSON happens occasionally (always just after "format":). Temperature 0 would repeat
        # the same output, so the retry samples at 0.7.
        for attempt, temp in ((1, 0.0), (2, 0.7)):
            try:
                scores, res = await llm.chat_json([{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": prompt}],
                                                  JUDGE_SCHEMA, alias=judge_alias, temperature=temp, max_tokens=1500,
                                                  **({"reasoning_effort": "medium"} if judge_alias == "hero" else {}))
                break
            except Exception as exc:  # noqa: BLE001
                raw = getattr(exc, "raw", "")
                print(f"  {row['item_id']} {row['alias']}: judge error (attempt {attempt}) {type(exc).__name__}: {exc}"
                      + (f" | raw: {raw[:160]!r}" if raw else ""), flush=True)
        if scores is None:
            continue
        scores["judge_model"] = res.model
        with db.connect() as conn:
            conn.execute("UPDATE eval.outputs SET judge=%s WHERE id=%s", (json.dumps(scores, ensure_ascii=False), row["id"]))
        print(f"  {row['item_id']:7} {row['alias']:14} C{scores['correctness']} A{scores['arabic']} F{scores['format']}", flush=True)


SUMMARY_SQL = """
    WITH h AS (SELECT output_id, avg(correctness) c, avg(arabic) a, avg(format) f
               FROM eval.human_scores GROUP BY output_id)
    SELECT o.alias, max(o.model) AS model, count(*) AS answers,
           round(avg(o.tokens_per_s)::numeric, 1) AS tok_s,
           round(avg(o.latency_ms)::numeric) AS latency_ms,
           sum(CASE WHEN o.auto_pass THEN 1 ELSE 0 END) AS auto_pass,
           count(o.auto_pass) AS auto_total,
           round(avg((o.judge->>'correctness')::int)::numeric, 2) AS j_correct,
           round(avg((o.judge->>'arabic')::int)::numeric, 2) AS j_arabic,
           round(avg((o.judge->>'format')::int)::numeric, 2) AS j_format,
           round(avg(h.c)::numeric, 2) AS h_correct,
           round(avg(h.a)::numeric, 2) AS h_arabic,
           round(avg(h.f)::numeric, 2) AS h_format,
           count(h.output_id) AS human_scored
    FROM eval.outputs o LEFT JOIN h ON h.output_id = o.id
    {where}
    GROUP BY o.alias ORDER BY o.alias"""


def summary_rows(item_ids: list[str] | None = None) -> list[dict]:
    with db.connect() as conn:
        if item_ids is None:
            return conn.execute(SUMMARY_SQL.format(where="")).fetchall()
        return conn.execute(SUMMARY_SQL.format(where="WHERE o.item_id = ANY(%s)"), (item_ids,)).fetchall()


def lock() -> str:
    """config/models.lock content from the current results (written by `make models-lock`)."""
    from datetime import date

    from app.main import MODEL_NAMES, results  # local import: main imports this module

    res = results()
    rec = res["recommendation"] or {}
    rows = {r["alias"]: r for r in res["models"]}
    out = [f"# Frozen by the week-1 Arabic gate on {date.today():%Y-%m-%d} (PLAN.md §5). Source: {rec.get('source')} scores.",
           "# Scores are means of correctness / Arabic quality / format (1-5); speeds are single-user on one GB10.", "roles:"]
    roles = {"workhorse": rec.get("workhorse", "workhorse"), "vision": rec.get("workhorse", "workhorse"), "hero": "hero"}
    if rec.get("keep_quality"):
        roles["quality"] = "quality"
    for role, alias in roles.items():
        r = rows.get(alias, {})
        out.append(f"  {role}: {{ alias: {alias}, model: \"{MODEL_NAMES.get(alias, alias)}\", "
                   f"human: {r.get('human_mean')}, judge: {r.get('judge_mean')}, tok_s: {r.get('tok_s')} }}")
    if not rec.get("keep_quality"):
        out.append("  quality: { alias: workhorse, note: \"Gemma 4 31B dropped: not ≥0.5 better on D5 legal items\" }")
    out.append("candidates:")
    for alias, r in rows.items():
        out.append(f"  {alias}: {{ model: \"{MODEL_NAMES.get(alias, alias)}\", human: {r.get('human_mean')}, "
                   f"judge: {r.get('judge_mean')}, auto: \"{r['auto_pass']}/{r['auto_total']}\", tok_s: {r['tok_s']} }}")
    out.append("notes:")
    out += [f"  - \"{n}\"" for n in rec.get("notes", [])]
    return "\n".join(out) + "\n"


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--models", required=True)
    r.add_argument("--only", default="")
    j = sub.add_parser("judge")
    j.add_argument("--judge", default="hero")
    j.add_argument("--force", action="store_true")
    j.add_argument("--only", default="")
    sub.add_parser("summary")
    sub.add_parser("lock")
    a = p.parse_args()
    if a.cmd == "run":
        asyncio.run(run(a.models.split(","), set(a.only.split(",")) if a.only else None))
    elif a.cmd == "judge":
        asyncio.run(judge(a.judge, a.force, set(a.only.split(",")) if a.only else None))
    elif a.cmd == "lock":
        print(lock(), end="")
    else:
        for row in summary_rows():
            print(row)


if __name__ == "__main__":
    main()
