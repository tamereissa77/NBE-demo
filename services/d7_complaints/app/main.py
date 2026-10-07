"""D7 · Complaints Personalisation (PLAN.md §4 D7).

Incoming complaints are classified (topic, severity, sentiment, vulnerable customer), given an SLA,
routed to a team, matched with similar past complaints, and given an empathetic, policy-checked draft
reply. Nothing is ever sent automatically: every draft waits for a human decision.

Policy rules here are synthetic placeholders until NBE supplies its real ones (the UI says so).
"""
import asyncio
import json
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row
from pydantic import BaseModel

from nbe_core import create_app, llm, platform, retrieval, settings
from nbe_core.audit import log_event
from nbe_core.text import strip_preamble
from nbe_core.trace import Trace

SEED = Path("/data/seed/d7")
COLLECTION = "d7_complaints"
TOPICS = ["cards", "fees", "transfers", "loans", "digital", "branch", "fraud", "accounts"]
TOPIC_AR = {"cards": "البطاقات", "fees": "الرسوم والخصومات", "transfers": "التحويلات", "loans": "التمويل", "digital": "القنوات الرقمية",
            "branch": "الفروع وخدمة العملاء", "fraud": "الاحتيال", "accounts": "الحسابات"}
TEAMS = {"cards": "إدارة البطاقات", "fees": "إدارة العمليات - المطابقة", "transfers": "إدارة التحويلات", "loans": "إدارة التمويل الشخصي",
         "digital": "دعم القنوات الرقمية", "branch": "إدارة جودة الفروع", "fraud": "وحدة مكافحة الاحتيال", "accounts": "إدارة الحسابات"}
SLA_HOURS = {4: 4, 3: 24, 2: 72, 1: 120}          # synthetic policy: hours to first response by severity
POLICY_RULES = [  # synthetic placeholders until NBE's real rules are supplied
    "اعتذر بوضوح وأظهر التعاطف دون لوم العميل.",
    "لا تعد برد مبالغ أو تعويض أو موافقة قبل انتهاء التحقق؛ قل إن الحالة قيد المراجعة.",
    "اذكر رقم الشكوى والمدة المتوقعة للرد حسب مستوى الخدمة.",
    "لا تطلب من العميل الرقم السري أو رمز التحقق أو بيانات البطاقة الكاملة.",
    "في شكاوى الاحتيال: انصح بإيقاف البطاقة فوراً واذكر أن وحدة مكافحة الاحتيال تتابع.",
    "إذا كان العميل في ظرف إنساني صعب فأولِ الحالة أولوية واعرض اتصالاً هاتفياً.",
    "اكتب بلغة العميل: الفصحى المبسطة للعربية (حتى لو كتب بالعامية)، والإنجليزية للإنجليزية.",
]
# Promises and requests for secrets. Advice such as "never share your PIN" is fine; asking for it is not.
BANNED = [r"نضمن", r"مضمون", r"سنرد المبلغ", r"سيتم رد المبلغ", r"سنعوضك", r"\bguarantee", r"we will refund", r"you will be refunded",
          r"(send|share|provide|confirm|give)\s+(us\s+)?(your\s+)?(PIN|OTP|password|full card number)",
          r"(أرسل|أرسلي|زودنا|زوّدنا|أخبرنا|اذكر)\S*\s+(لنا\s+)?(ب)?(الرقم السري|رمز التحقق|كلمة المرور|رقم البطاقة كاملاً)"]

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS d7;
CREATE TABLE IF NOT EXISTS d7.complaints (id TEXT PRIMARY KEY, channel TEXT, lang TEXT, customer_name TEXT, text TEXT,
    label_topic TEXT, label_severity INT, label_sentiment TEXT, label_callback BOOLEAN, vulnerable BOOLEAN,
    received_at TIMESTAMPTZ, in_queue BOOLEAN DEFAULT false);
CREATE TABLE IF NOT EXISTS d7.triage (id TEXT PRIMARY KEY REFERENCES d7.complaints, result JSONB, status TEXT,
    decided_by TEXT, decided_at TIMESTAMPTZ, final_reply TEXT, updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS d7.cache (key TEXT PRIMARY KEY, value JSONB);
"""


def db():
    return psycopg.connect(settings.postgres_dsn, row_factory=dict_row, autocommit=True)


@asynccontextmanager
async def lifespan(_app):
    with db() as conn:
        conn.execute(SCHEMA)
    yield


app = create_app("d7", "Complaints Personalization", phase="wave1")
app.router.lifespan_context = lifespan


@app.post("/admin/ingest")
async def ingest():
    rows = [json.loads(line) for line in (SEED / "complaints.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    queue = set(json.loads((SEED / "demo_queue.json").read_text()))
    now = datetime.now(timezone.utc)
    with db() as conn:
        conn.execute("TRUNCATE d7.triage, d7.complaints, d7.cache")
        for i, r in enumerate(rows):
            received = now - timedelta(days=(i * 7) % 84, hours=(i * 5) % 24) if r["id"] not in queue else now - timedelta(minutes=5 * (i % 50))
            conn.execute("INSERT INTO d7.complaints VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                         (r["id"], r["channel"], r["lang"], r["customer_name"], r["text"], r["topic"], r["severity"],
                          r["sentiment"], r["needs_callback"], r["vulnerable"], received, r["id"] in queue))
    await retrieval.ensure_collection(COLLECTION, recreate=True)
    await retrieval.upsert(COLLECTION, [r["text"] for r in rows], [{"id": r["id"], "topic": r["topic"]} for r in rows])
    return {"complaints": len(rows), "queue": len(queue)}


@app.post("/admin/reset")
def reset():
    """Between audiences: clear triage results and decisions, refresh queue arrival times; keep the data and caches."""
    with db() as conn:
        conn.execute("TRUNCATE d7.triage")
        # Fresh arrival times for the demo queue (5 minutes apart), so SLA countdowns start fresh per audience
        conn.execute("""UPDATE d7.complaints c SET received_at = now() - interval '5 minutes' * q.rn
                        FROM (SELECT id, row_number() OVER (ORDER BY id) AS rn FROM d7.complaints WHERE in_queue) q
                        WHERE c.id = q.id""")
    return {"reset": True}


def _row_out(r: dict) -> dict:
    t = r.get("result")
    return {"id": r["id"], "channel": r["channel"], "lang": r["lang"], "customer_name": r["customer_name"], "text": r["text"],
            "received_at": r["received_at"].isoformat(), "status": r.get("status") or "new", "triage": t,
            "final_reply": r.get("final_reply"), "decided_by": r.get("decided_by")}


@app.get("/queue")
def queue():
    with db() as conn:
        rows = conn.execute("""SELECT c.*, t.result, t.status, t.final_reply, t.decided_by FROM d7.complaints c
                               LEFT JOIN d7.triage t ON t.id = c.id WHERE c.in_queue ORDER BY c.received_at""").fetchall()
    out = [_row_out(r) for r in rows]
    # Prioritised view: triaged items by SLA deadline first, untriaged after
    out.sort(key=lambda x: (x["triage"] is None, (x["triage"] or {}).get("sla_due", ""), x["received_at"]))
    return out


CLASSIFY_SCHEMA = {"type": "object", "properties": {
    "topic": {"type": "string", "enum": TOPICS}, "severity": {"type": "integer", "minimum": 1, "maximum": 4},
    "sentiment": {"type": "string", "enum": ["negative", "neutral", "positive"]}, "vulnerable": {"type": "boolean"},
    "needs_callback": {"type": "boolean"}, "summary": {"type": "string"}, "language": {"type": "string", "enum": ["msa", "egy", "en"]}},
    "required": ["topic", "severity", "sentiment", "vulnerable", "needs_callback", "summary", "language"]}

CLASSIFY_PROMPT = ("صنّف شكوى عميل بنك. topic واحد من: " + ", ".join(f"{k} ({v})" for k, v in TOPIC_AR.items()) +
                   ". severity: 1 استفسار بسيط، 2 إزعاج دون خسارة كبيرة، 3 خسارة مالية أو تعطل خدمة مهمة، 4 احتيال أو خسارة كبيرة أو ظرف إنساني عاجل. "
                   "vulnerable: العميل في ظرف إنساني صعب (مرض، سن متقدم، حاجة عاجلة). needs_callback: الخطورة 3 أو أكثر أو عميل في ظرف صعب. "
                   "summary: جملة واحدة بالعربية. language: msa أو egy أو en.\n\nالشكوى:\n")


async def classify(text: str):
    return await llm.chat_json([{"role": "user", "content": CLASSIFY_PROMPT + text}], CLASSIFY_SCHEMA, max_tokens=300)


def policy_violations(text: str) -> list[str]:
    return [p for p in BANNED if re.search(p, text, re.I)]


@app.post("/triage/{cid}")
async def triage(cid: str):
    with db() as conn:
        c = conn.execute("SELECT * FROM d7.complaints WHERE id=%s", (cid,)).fetchone()
    if not c:
        raise HTTPException(404, "unknown complaint")
    trace = Trace()
    cls, res = await classify(c["text"])
    trace.llm("Classify topic, severity, sentiment (zero-shot, workhorse)", res)
    sla_h = SLA_HOURS[cls["severity"]] if not cls["vulnerable"] else min(SLA_HOURS[cls["severity"]], 24)
    due = c["received_at"] + timedelta(hours=sla_h)
    team = TEAMS[cls["topic"]]
    trace.add("rules", "SLA and routing rules", {"sla_hours": sla_h, "team": team})

    with trace.step("retrieval", "Similar past complaints (bge-m3)") as s:
        hits = await retrieval.search(COLLECTION, c["text"], k=4, candidates=12)
        similar = [{"id": h["id"], "topic": h["topic"], "text": h["text"][:220], "score": h["rerank_score"]} for h in hits if h["id"] != cid][:3]
        s["detail"] = similar

    lang_note = "اكتب الرد بالإنجليزية." if cls["language"] == "en" else "اكتب الرد بالعربية الفصحى المبسطة."
    prompt = ("اكتب رد خدمة العملاء على الشكوى التالية. أخرج نص الرد فقط، بدون أي مقدمة أو عنوان أو بدائل أو تنسيق Markdown.\n"
              f"رقم الشكوى: {cid}. الفريق المختص: {team}. موعد الرد الأول المتوقع: خلال {sla_h} ساعة.\n"
              "سياسة الردود (إلزامية):\n" + "\n".join(f"- {r}" for r in POLICY_RULES) + f"\n{lang_note}\n\n"
              f"الشكوى ({c['customer_name']}):\n{c['text']}")
    draft = ""
    violations: list[str] = []
    for attempt in (1, 2):
        r = await llm.chat([{"role": "user", "content": prompt + ("" if attempt == 1 else
                            "\n\nتنبيه: المسودة السابقة خالفت السياسة بعبارات: " + "، ".join(violations) + ". أعد الكتابة دون أي وعد أو طلب بيانات حساسة.")}],
                           max_tokens=600, temperature=0.3)
        trace.llm(f"Draft reply (attempt {attempt})", r)
        draft = strip_preamble(r.text)
        violations = policy_violations(draft)
        if not violations:
            break
    guard = await platform.guard_output(draft, user=c["text"])
    trace.add("guardrail", "Output guardrail (NeMo self-check)", guard, guard["latency_ms"])

    result = {**cls, "topic_ar": TOPIC_AR[cls["topic"]], "team": team, "sla_hours": sla_h, "sla_due": due.isoformat(),
              "similar": similar, "draft": draft, "policy_ok": not violations, "policy_violations": violations,
              "guardrail": {"allowed": guard["allowed"], "rail": guard["rail"]},
              "labels": {"topic": c["label_topic"], "severity": c["label_severity"]}, "trace": trace.to_list()}
    with db() as conn:
        conn.execute("""INSERT INTO d7.triage (id, result, status) VALUES (%s,%s,'awaiting_human')
                        ON CONFLICT (id) DO UPDATE SET result=EXCLUDED.result, status='awaiting_human', final_reply=NULL,
                            decided_by=NULL, decided_at=NULL, updated_at=now()""", (cid, json.dumps(result, ensure_ascii=False)))
    await log_event("triage", "workhorse", {"id": cid, "topic": cls["topic"], "severity": cls["severity"]})
    return result


@app.post("/triage-all")
async def triage_all():
    ids = [r["id"] for r in queue() if r["status"] == "new"]
    sem = asyncio.Semaphore(4)

    async def one(i):
        async with sem:
            return await triage(i)
    await asyncio.gather(*(one(i) for i in ids))
    return {"triaged": len(ids)}


class Decision(BaseModel):
    action: str            # approve | edit | escalate
    reviewer: str = "reviewer"
    text: str | None = None


@app.post("/decision/{cid}")
async def decision(cid: str, d: Decision):
    if d.action not in ("approve", "edit", "escalate"):
        raise HTTPException(400, "action must be approve, edit or escalate")
    with db() as conn:
        t = conn.execute("SELECT result FROM d7.triage WHERE id=%s", (cid,)).fetchone()
        if not t:
            raise HTTPException(409, "triage the complaint first")
        final = d.text if d.action == "edit" and d.text else t["result"]["draft"]
        if d.action in ("approve", "edit") and policy_violations(final):
            raise HTTPException(422, f"reply violates policy: {policy_violations(final)}")
        status = {"approve": "approved", "edit": "approved_edited", "escalate": "escalated"}[d.action]
        conn.execute("UPDATE d7.triage SET status=%s, final_reply=%s, decided_by=%s, decided_at=now() WHERE id=%s",
                     (status, final if d.action != "escalate" else None, d.reviewer, cid))
    await log_event("human_decision", d.reviewer, {"id": cid, "action": d.action})
    return {"id": cid, "status": status}


def kmeans(x: np.ndarray, k: int, iters: int = 30, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    centers = x[rng.choice(len(x), k, replace=False)]
    for _ in range(iters):
        labels = np.argmax(x @ centers.T, axis=1)          # cosine (vectors are normalised)
        new = np.stack([x[labels == j].mean(0) if (labels == j).any() else centers[j] for j in range(k)])
        centers = new / np.linalg.norm(new, axis=1, keepdims=True)
    return labels


@app.get("/trends")
async def trends(refresh: bool = False):
    with db() as conn:
        cached = conn.execute("SELECT value FROM d7.cache WHERE key='trends'").fetchone()
        if cached and not refresh:
            return cached["value"]
        rows = conn.execute("SELECT id, text, label_topic, label_severity, received_at FROM d7.complaints ORDER BY id").fetchall()
    vecs = np.array(await retrieval.embed([r["text"] for r in rows]), dtype=np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    labels = kmeans(vecs, 10)

    async def name(j):
        members = [rows[i] for i in np.where(labels == j)[0]]
        sample = "\n".join(f"- {m['text'][:160]}" for m in members[:12])
        r = await llm.chat([{"role": "user", "content": "أعط اسماً قصيراً (3 إلى 6 كلمات) يصف الموضوع المشترك لهذه الشكاوى، بالعربية، دون مقدمة:\n" + sample}],
                           max_tokens=30, temperature=0)
        weeks: dict[str, int] = {}
        for m in members:
            wk = m["received_at"].strftime("%G-W%V")
            weeks[wk] = weeks.get(wk, 0) + 1
        return {"cluster": int(j), "name": r.text.strip().strip("\"'"), "count": len(members),
                "avg_severity": round(float(np.mean([m["label_severity"] for m in members])), 2),
                "top_topic": max(set(m["label_topic"] for m in members), key=[m["label_topic"] for m in members].count),
                "weekly": dict(sorted(weeks.items())), "examples": [m["text"][:200] for m in members[:3]]}
    clusters = sorted(await asyncio.gather(*(name(j) for j in range(10))), key=lambda c: -c["count"])
    by_topic = {t: sum(1 for r in rows if r["label_topic"] == t) for t in TOPICS}
    value = {"total": len(rows), "clusters": clusters, "by_topic": by_topic, "topic_ar": TOPIC_AR}
    with db() as conn:
        conn.execute("INSERT INTO d7.cache VALUES ('trends', %s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
                     (json.dumps(value, ensure_ascii=False, default=str),))
    return value


@app.get("/accuracy")
async def accuracy(refresh: bool = False, n: int = 100):
    """Zero-shot classification against the synthetic labels on a held-out sample (not the demo queue)."""
    with db() as conn:
        cached = conn.execute("SELECT value FROM d7.cache WHERE key='accuracy'").fetchone()
        if cached and not refresh:
            return cached["value"]
        rows = conn.execute("SELECT id, text, label_topic, label_severity FROM d7.complaints WHERE NOT in_queue ORDER BY id LIMIT %s", (n,)).fetchall()
    sem = asyncio.Semaphore(4)

    async def one(r):
        async with sem:
            cls, res = await classify(r["text"])
            return r, cls, res.latency_ms
    out = await asyncio.gather(*(one(r) for r in rows))
    topic_ok = sum(c["topic"] == r["label_topic"] for r, c, _ in out)
    sev_ok = sum(abs(c["severity"] - r["label_severity"]) <= 1 for r, c, _ in out)
    confusion: dict[str, dict[str, int]] = {}
    for r, c, _ in out:
        confusion.setdefault(r["label_topic"], {}).setdefault(c["topic"], 0)
        confusion[r["label_topic"]][c["topic"]] += 1
    value = {"n": len(out), "topic_accuracy": round(topic_ok / len(out), 3), "severity_within_1": round(sev_ok / len(out), 3),
             "avg_latency_ms": int(np.mean([ms for *_, ms in out])), "confusion": confusion,
             "note": "Synthetic labels by construction; zero-shot workhorse, no fine-tuning."}
    with db() as conn:
        conn.execute("INSERT INTO d7.cache VALUES ('accuracy', %s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
                     (json.dumps(value),))
    return value


@app.get("/policy")
def policy():
    return {"rules": POLICY_RULES, "sla_hours": SLA_HOURS, "teams": TEAMS, "note": "Synthetic placeholder policy until NBE supplies its rules."}
