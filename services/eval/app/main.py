"""Arabic gate scoring API, behind the gateway at /api/eval.

Scorers see answers blind: each prompt's answers are shuffled per scorer and labelled A, B, C...
with opaque ids; model names appear only on /results. Judge scores are returned for an item only
after the scorer has scored it, so the judge cannot anchor the human.
"""
import csv
import io
import random
from contextlib import asynccontextmanager

from fastapi import HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from nbe_core import create_app
from app import db
from app.gate import build_messages, load, summary_rows

CORE = ["workhorse", "quality", "hero"]                 # deployable candidates (scored by humans)
REFERENCE = ["ref-qwen14b", "ref-mistral7b"]            # references, incl. NBE's listed Mistral-7B
MODEL_NAMES = {
    "workhorse": "Gemma 4 26B-A4B (FP8)", "quality": "Gemma 4 31B (NVFP4)", "hero": "gpt-oss-120b",
    "ref-qwen14b": "Qwen2.5-14B-Instruct", "ref-mistral7b": "Mistral-7B-Instruct v0.3 (NBE list)",
}
MIN_TOKS_WORKHORSE = 20        # interactive demos need at least this decode speed


@asynccontextmanager
async def lifespan(_app):
    db.init()
    yield


app = create_app("eval", "Arabic gate", phase="gate")
app.router.lifespan_context = lifespan


class ScoreIn(BaseModel):
    scorer: str = Field(min_length=1, max_length=60)
    output_id: str
    correctness: int = Field(ge=1, le=5)
    arabic: int = Field(ge=1, le=5)
    format: int = Field(ge=1, le=5)
    note: str = ""


@app.get("/items")
def items(scorer: str, set: str = "core"):
    data = load()
    aliases = CORE if set == "core" else CORE + REFERENCE
    with db.connect() as conn:
        outs = conn.execute("SELECT id, item_id, alias, text, tool_calls, auto_pass, auto_detail, judge "
                            "FROM eval.outputs WHERE alias = ANY(%s)", (aliases,)).fetchall()
        mine = {r["output_id"]: r for r in conn.execute(
            "SELECT output_id, correctness, arabic, format, note FROM eval.human_scores WHERE scorer=%s", (scorer,)).fetchall()}
    by_item: dict[str, list] = {}
    for o in outs:
        by_item.setdefault(o["item_id"], []).append(o)

    result = []
    for item in data["items"]:
        answers = by_item.get(item["id"], [])
        random.Random(f"{scorer}:{item['id']}").shuffle(answers)
        msgs, tools = build_messages(item, data)
        scored_all = bool(answers) and all(a["id"] in mine for a in answers)
        result.append({
            "id": item["id"], "dialect": item["dialect"], "demo": item["demo"], "task": item["task"], "title": item["title"],
            "messages": msgs, "tools": [t["function"]["name"] for t in tools] if tools else [], "good": item["good"],
            "answers": [{
                "output_id": a["id"], "label": chr(65 + i), "text": a["text"], "tool_calls": a["tool_calls"],
                "auto_pass": a["auto_pass"], "auto_detail": a["auto_detail"],
                "judge": a["judge"] if scored_all else None,           # revealed only after scoring
                "mine": mine.get(a["id"]),
            } for i, a in enumerate(answers)],
        })
    return {"scorer": scorer, "set": set, "items": result}


@app.post("/scores")
def save_score(s: ScoreIn):
    with db.connect() as conn:
        if not conn.execute("SELECT 1 FROM eval.outputs WHERE id=%s", (s.output_id,)).fetchone():
            raise HTTPException(404, "unknown output")
        conn.execute("""INSERT INTO eval.human_scores (scorer, output_id, correctness, arabic, format, note)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (scorer, output_id) DO UPDATE SET correctness=EXCLUDED.correctness,
                            arabic=EXCLUDED.arabic, format=EXCLUDED.format, note=EXCLUDED.note, updated_at=now()""",
                     (s.scorer.strip(), s.output_id, s.correctness, s.arabic, s.format, s.note))
    return {"saved": True}


def _mean(row: dict, prefix: str) -> float | None:
    vals = [row[f"{prefix}_{k}"] for k in ("correct", "arabic", "format")]
    return round(sum(float(v) for v in vals) / 3, 2) if all(v is not None for v in vals) else None


def recommendation(overall: list[dict], legal: list[dict]) -> dict:
    """Decision rule written down before any scores exist (PLAN.md §5)."""
    by = {r["alias"]: r for r in overall}
    leg = {r["alias"]: r for r in legal}
    human_cov = min((by[a]["human_scored"] / max(by[a]["answers"], 1) for a in CORE if a in by), default=0)
    source = "h" if human_cov >= 0.8 else "j"
    notes = [] if source == "h" else ["Provisional: human scoring covers less than 80% of answers, so this uses the LLM judge."]

    def score(alias, rows=by):
        return _mean(rows[alias], source) if alias in rows else None

    if score("workhorse") is None:
        return {"source": "none", "workhorse": None, "workhorse_model": None, "keep_quality": None, "hero": "hero",
                "notes": ["Pending: no judge or human scores yet. Run the judge (make arabic-gate) or score at /eval."]}

    eligible = [a for a in ["workhorse"] + REFERENCE if a in by and (by[a]["tok_s"] or 0) >= MIN_TOKS_WORKHORSE and score(a) is not None]
    workhorse = max(eligible, key=score, default="workhorse")
    w_legal, q_legal = score(workhorse, leg), score("quality", leg)
    keep_quality = q_legal is not None and w_legal is not None and q_legal - w_legal >= 0.5
    notes.append(f"Workhorse: highest {'human' if source == 'h' else 'judge'} mean among models at ≥{MIN_TOKS_WORKHORSE} tok/s.")
    notes.append(f"Quality model kept only if it beats the workhorse by ≥0.5 on the D5 legal items "
                 f"(quality {q_legal}, workhorse {w_legal}).")
    return {"source": "human" if source == "h" else "judge", "workhorse": workhorse, "workhorse_model": MODEL_NAMES.get(workhorse),
            "keep_quality": keep_quality, "hero": "hero", "notes": notes}


@app.get("/results")
def results():
    data = load()
    ids = lambda pred: [i["id"] for i in data["items"] if pred(i)]  # noqa: E731
    order = {a: i for i, a in enumerate(CORE + REFERENCE)}
    by_order = lambda rows: sorted(rows, key=lambda r: order.get(r["alias"], 99))  # noqa: E731
    overall = by_order(summary_rows())
    by_dialect = {d: by_order(summary_rows(ids(lambda i, d=d: i["dialect"] == d))) for d in ("msa", "egy", "mix")}
    legal = by_order(summary_rows(ids(lambda i: i["demo"] == "D5")))
    for row in overall:
        row["name"] = MODEL_NAMES.get(row["alias"], row["alias"])
        row["human_mean"], row["judge_mean"] = _mean(row, "h"), _mean(row, "j")
    with db.connect() as conn:
        scorers = [r["scorer"] for r in conn.execute("SELECT DISTINCT scorer FROM eval.human_scores ORDER BY 1")]
    return {"models": overall, "by_dialect": by_dialect, "legal": legal, "scorers": scorers,
            "recommendation": recommendation(overall, legal) if overall else None}


@app.get("/export.csv", response_class=PlainTextResponse)
def export_csv():
    with db.connect() as conn:
        rows = conn.execute("""SELECT o.item_id, o.alias, o.model, o.latency_ms, o.tokens_per_s, o.auto_pass, o.auto_detail,
                                      o.judge->>'correctness' AS judge_correctness, o.judge->>'arabic' AS judge_arabic,
                                      o.judge->>'format' AS judge_format, o.judge->>'rationale' AS judge_rationale,
                                      h.scorer, h.correctness, h.arabic, h.format, h.note, o.text
                               FROM eval.outputs o LEFT JOIN eval.human_scores h ON h.output_id = o.id
                               ORDER BY o.item_id, o.alias, h.scorer""").fetchall()
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return PlainTextResponse("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=arabic_gate.csv"})
