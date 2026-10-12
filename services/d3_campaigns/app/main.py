"""D3 · Campaigns & Offers hyper-personalisation (PLAN.md §4 D3).

Marketing picks a synthetic segment. The system profiles interests from transactions (SQL), matches a
partner merchant, writes Arabic and English copy for SMS, email and social, checks it against
compliance rules (and fixes it), renders a banner mock-up and proposes an A/B test with a real
sample-size calculation. Merchant contracts and deal costing are out of scope, as the brief says.
"""
import asyncio
import base64
import csv
import json
import math
import os
import re
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

import httpx
import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row
from pydantic import BaseModel

from nbe_core import create_app, llm, retrieval, settings
from nbe_core import locale as L
from nbe_core.trace import Trace

DATA = Path("/data/generated/d3")
BANNERS = DATA / "banners"
SDXL_URL = "http://nbe-sdxl:8000"
COLLECTION = "d3_merchants"
TODAY = date(2026, 10, 7)
# Banner colours follow the brand pack (BANNER_PALETTE in .env)
PALETTE = os.getenv("BANNER_PALETTE", "warm green and golden orange colour palette")

OFFER = L.D3_OFFER   # category -> cashback % and cap in local currency (synthetic offer rules)
BANNER_SCENE = {
    "grocery": "a bright modern supermarket aisle with fresh produce", "dining": L.DINING_SCENE,
    "cafe": "a cozy modern café with coffee cups on a wooden table", "fashion": "a stylish clothing boutique with elegant outfits",
    "electronics": "a sleek electronics store with smartphones and laptops", "travel": "an airplane wing above clouds at golden hour",
    "hotels": L.RESORT_SCENE, "fuel": "a clean modern fuel station at dusk with a car",
    "pharmacy": "a clean bright pharmacy interior", "education": "a bright classroom with books and a laptop",
    "home": "a modern living room with stylish furniture", "telecom": "a smartphone with signal icons on a clean background",
}
REQUIRED = {"ar": "تطبق الشروط والأحكام", "en": "T&Cs apply"}
BANNED = [r"مضمون", r"100\s*%", r"أفضل من", r"أفضل بنك", r"مجاناً? تماماً", r"بدون أي شروط", r"guarantee", r"risk[- ]free", r"best bank", r"no conditions"]


def db():
    return psycopg.connect(settings.postgres_dsn, row_factory=dict_row, autocommit=True)


@asynccontextmanager
async def lifespan(_app):
    with db() as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS d3")
    yield


app = create_app("d3", "Campaigns & Offers", phase="wave2")
app.router.lifespan_context = lifespan


@app.post("/admin/ingest")
async def ingest():
    with db() as conn:
        conn.execute("""DROP TABLE IF EXISTS d3.transactions, d3.customers, d3.merchants;
            CREATE TABLE d3.merchants (id TEXT PRIMARY KEY, name_ar TEXT, category TEXT, category_ar TEXT, category_en TEXT, mcc TEXT,
                city TEXT, description_ar TEXT, partner BOOLEAN);
            CREATE TABLE d3.customers (id TEXT PRIMARY KEY, name_ar TEXT, persona TEXT, persona_ar TEXT, age INT, gender TEXT, city TEXT,
                income_band TEXT, cards TEXT, lang TEXT, opt_in_sms BOOLEAN, opt_in_email BOOLEAN);
            CREATE TABLE d3.transactions (id INT PRIMARY KEY, customer_id TEXT, merchant_id TEXT, ts TIMESTAMP, amount NUMERIC(12,2), channel TEXT);""")
        for table in ("merchants", "customers", "transactions"):
            with open(DATA / f"{table}.csv", encoding="utf-8") as f:
                header = next(csv.reader(f))
                with conn.cursor().copy(f"COPY d3.{table} ({', '.join(header)}) FROM STDIN WITH (FORMAT csv)") as cp:
                    for line in f:
                        cp.write(line)
        conn.execute("CREATE INDEX ON d3.transactions (customer_id); CREATE INDEX ON d3.transactions (merchant_id); ANALYZE")
        merchants = conn.execute("SELECT * FROM d3.merchants").fetchall()
        counts = {t: conn.execute(f"SELECT count(*) AS n FROM d3.{t}").fetchone()["n"] for t in ("merchants", "customers", "transactions")}
    await retrieval.ensure_collection(COLLECTION, recreate=True)
    await retrieval.upsert(COLLECTION, [f"{m['name_ar']} - {m['category_ar']} ({m['category_en']}) - {m['city']}" for m in merchants],
                           [{"merchant_id": m["id"], "category": m["category"], "partner": m["partner"]} for m in merchants])
    return counts


@app.get("/segments")
def segments():
    with db() as conn:
        rows = conn.execute("""SELECT persona, persona_ar, count(*) AS customers, sum(opt_in_sms::int) AS sms, sum(opt_in_email::int) AS email
                               FROM d3.customers GROUP BY 1, 2 ORDER BY 3 DESC""").fetchall()
        cities = [r["city"] for r in conn.execute("SELECT city FROM d3.customers GROUP BY 1 ORDER BY count(*) DESC")]
    return {"segments": rows, "cities": cities}


def interest_profile(conn, persona: str, city: str | None) -> list[dict]:
    """Category share of spend in the segment versus all customers (lift)."""
    where, args = "c.persona = %s", [persona]
    if city:
        where += " AND c.city = %s"
        args.append(city)
    return conn.execute(f"""
        WITH seg AS (SELECT m.category, m.category_ar, sum(t.amount) AS spend, count(*) AS n
                     FROM d3.transactions t JOIN d3.customers c ON c.id = t.customer_id JOIN d3.merchants m ON m.id = t.merchant_id
                     WHERE {where} GROUP BY 1, 2),
             base AS (SELECT m.category, sum(t.amount) AS spend FROM d3.transactions t JOIN d3.merchants m ON m.id = t.merchant_id GROUP BY 1)
        SELECT * FROM (
            SELECT seg.category, seg.category_ar, seg.n AS transactions, round(seg.spend) AS spend,
                   round(100 * seg.spend / sum(seg.spend) OVER (), 1) AS share,
                   round((seg.spend / sum(seg.spend) OVER ()) / (base.spend / sum(base.spend) OVER ()), 2) AS lift
            FROM seg JOIN base USING (category)) p
        ORDER BY share * lift DESC""", args).fetchall()


class CampaignIn(BaseModel):
    persona: str
    city: str | None = None
    brief: str = ""
    stress_test: bool = False     # plant a non-compliant claim to show the compliance check catching it


COPY_SCHEMA = {"type": "object", "properties": {k: {"type": "string"} for k in (
    "sms_a_ar", "sms_b_ar", "sms_en", "email_subject_ar", "email_body_ar", "email_subject_en", "email_body_en", "social_local", "banner_headline_ar")},
    "required": ["sms_a_ar", "sms_b_ar", "sms_en", "email_subject_ar", "email_body_ar", "email_subject_en", "email_body_en", "social_local", "banner_headline_ar"]}


def compliance(copy: dict) -> list[dict]:
    issues = []
    for key, text in copy.items():
        if key == "banner_headline_ar":
            continue
        lang = "en" if key.endswith("_en") else "ar"
        if not key.startswith("email_subject") and REQUIRED[lang].lower() not in text.lower():
            issues.append({"field": key, "rule": "required_disclaimer", "detail": f"missing «{REQUIRED[lang]}»"})
        if key.startswith("sms") and len(text) > 160:
            issues.append({"field": key, "rule": "sms_length", "detail": f"{len(text)} characters (max 160)"})
        for pat in BANNED:
            if m := re.search(pat, text, re.I):
                issues.append({"field": key, "rule": "banned_claim", "detail": f"«{m.group(0)}»"})
    return issues


def sample_size(p1: float, rel_lift: float, alpha_z: float = 1.96, power_z: float = 0.8416) -> int:
    """Two-proportion test, per arm (alpha 0.05 two-sided, power 80%)."""
    p2 = p1 * (1 + rel_lift)
    return math.ceil((alpha_z + power_z) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2)) / (p2 - p1) ** 2)


async def banner(category: str, trace: Trace) -> dict:
    prompt = f"commercial banking advertisement photo, {BANNER_SCENE[category]}, {PALETTE}, bright, clean, professional, copy space on the right"
    try:
        async with httpx.AsyncClient(timeout=120) as c:
            if (await c.get(f"{SDXL_URL}/health", timeout=2)).status_code == 200:
                r = (await c.post(f"{SDXL_URL}/generate", json={"prompt": prompt, "steps": 22, "seed": 11})).json()
                trace.add("image", "Banner mock-up generated live (SDXL)", {"prompt": prompt}, r["latency_ms"])
                return {"png_base64": r["png_base64"], "source": "live", "prompt": prompt}
    except httpx.HTTPError:
        pass
    cached = BANNERS / f"{category}.png"
    if cached.exists():
        trace.add("image", "Banner mock-up from cache (SDXL not running: make image-on for live generation)", {"prompt": prompt})
        return {"png_base64": base64.b64encode(cached.read_bytes()).decode(), "source": "cache", "prompt": prompt}
    return {"png_base64": None, "source": "none", "prompt": prompt}


@app.post("/campaign")
async def campaign(body: CampaignIn):
    trace = Trace()
    with db() as conn:
        seg = conn.execute("""SELECT persona_ar, count(*) AS n, sum(opt_in_sms::int) AS sms, sum(opt_in_email::int) AS email,
                                     round(avg(age)) AS age FROM d3.customers WHERE persona=%s AND (%s::text IS NULL OR city=%s) GROUP BY 1""",
                          (body.persona, body.city, body.city)).fetchone()
        if not seg:
            raise HTTPException(404, "empty segment")
        with trace.step("sql", "Interest profile: category share of spend vs all customers (lift)") as s:
            profile = interest_profile(conn, body.persona, body.city)
            s["detail"] = profile[:5]
        top = profile[0]["category"]
        with trace.step("sql", "Merchant match: partner merchants where this segment spends most") as s:
            merchants = conn.execute("""SELECT m.id, m.name_ar, m.category, m.category_ar, m.city, round(sum(t.amount)) AS seg_spend, count(DISTINCT t.customer_id) AS seg_customers
                FROM d3.transactions t JOIN d3.customers c ON c.id = t.customer_id JOIN d3.merchants m ON m.id = t.merchant_id
                WHERE c.persona = %s AND (%s::text IS NULL OR c.city = %s) AND m.partner AND m.category = ANY(%s)
                GROUP BY 1, 2, 3, 4, 5 ORDER BY seg_spend DESC LIMIT 3""",
                (body.persona, body.city, body.city, [p["category"] for p in profile[:3]])).fetchall()
            s["detail"] = merchants
    if body.brief.strip():
        with trace.step("retrieval", "Brief → merchant search (bge-m3)") as s:
            hits = [h for h in await retrieval.search(COLLECTION, body.brief, k=6, candidates=20) if h["partner"]]
            s["detail"] = [h["text"] for h in hits[:3]]
        if hits:
            with db() as conn:
                m = conn.execute("SELECT id, name_ar, category, category_ar, city FROM d3.merchants WHERE id=%s", (hits[0]["merchant_id"],)).fetchone()
            merchants = [{**m, "seg_spend": None, "seg_customers": None}] + [x for x in merchants if x["id"] != m["id"]][:2]
    if not merchants:
        raise HTTPException(409, "no partner merchant for this segment")
    m = merchants[0]
    pct, cap = OFFER[m["category"]]
    end = (TODAY.replace(day=1) + timedelta(days=62)).replace(day=1) - timedelta(days=1)
    offer = {"merchant": m["name_ar"], "category_ar": m["category_ar"], "cashback_pct": pct, "cap": cap, "currency": L.CURRENCY, "valid_until": end.isoformat()}

    prompt = (f"اكتب محتوى حملة تسويقية لبنك {L.ADJ_AR} لشريحة «{seg['persona_ar']}» ({seg['n']} عميلاً، متوسط العمر {seg['age']}). "
              f"أهم اهتماماتهم حسب الإنفاق: " + "، ".join(p["category_ar"] for p in profile[:3]) + ".\n"
              f"العرض: استرداد نقدي {pct}% بحد أقصى {cap} {L.CURRENCY_AR} على المشتريات من «{m['name_ar']}» ({m['category_ar']}) ببطاقات البنك حتى {end.isoformat()}.\n"
              "المطلوب (أخرج JSON فقط):\n"
              "- sms_a_ar و sms_b_ar: رسالتان قصيرتان بالعربية لاختبار A/B (أ: تركّز على الفائدة، ب: تركّز على قِصر المدة)، كل منهما 160 حرفاً كحد أقصى وتنتهي بـ «تطبق الشروط والأحكام».\n"
              "- sms_en: رسالة إنجليزية 160 حرفاً كحد أقصى تنتهي بـ «T&Cs apply».\n"
              "- email_subject_ar و email_body_ar (80 إلى 120 كلمة، تنتهي بـ «تطبق الشروط والأحكام»).\n"
              "- email_subject_en و email_body_en (ترجمة، تنتهي بـ «T&Cs apply»).\n"
              f"- social_local: منشور قصير {L.SOCIAL_STYLE_AR} ينتهي بـ «تطبق الشروط والأحكام».\n"
              "- banner_headline_ar: عنوان إعلاني من 3 إلى 6 كلمات.\n"
              "قواعد: لا وعود مضمونة، لا مقارنة بالمنافسين، لا مبالغة، اذكر النسبة والحد الأقصى والتاجر وتاريخ الانتهاء بدقة." +
              ("\n(اختبار ضغط للامتثال: أدرج عمداً في sms_a_ar عبارة «عائد مضمون 100%»)." if body.stress_test else "") +
              (f"\nتوجيه إضافي من فريق التسويق: {body.brief}" if body.brief.strip() else ""))
    copy, res = await llm.chat_json([{"role": "user", "content": prompt}], COPY_SCHEMA, max_tokens=1800, temperature=0.5)
    trace.llm("Write AR/EN copy for SMS, email and social (workhorse)", res)
    issues = compliance(copy)
    trace.add("rules", f"Compliance check: {len(issues)} issue(s)", issues)
    first_issues, fixed = issues, False
    if issues:
        fix_prompt = ("صحّح محتوى الحملة التالي ليزيل كل المخالفات المذكورة فقط، مع الحفاظ على باقي النص. أخرج نفس JSON.\n"
                      "المخالفات:\n" + "\n".join(f"- {i['field']}: {i['rule']} {i['detail']}" for i in issues) +
                      "\nتذكير: كل رسالة SMS بحد أقصى 160 حرفاً وتنتهي بالعبارة المطلوبة؛ ممنوع: مضمون، 100%، أفضل من، guarantee.\n\n" +
                      json.dumps(copy, ensure_ascii=False))
        copy, res = await llm.chat_json([{"role": "user", "content": fix_prompt}], COPY_SCHEMA, max_tokens=1800, temperature=0)
        trace.llm("Fix compliance issues (workhorse)", res)
        issues, fixed = compliance(copy), True
        trace.add("rules", f"Compliance re-check: {len(issues)} issue(s)", issues)
    img = await banner(m["category"], trace)

    # A/B design sized to the real audience: 10% holdout, the rest split evenly between A and B.
    audience = seg["sms"]
    baseline = 0.08                                   # synthetic assumption: targeted cashback redemption in 30 days
    per_arm_available = int(audience * 0.9 / 2)
    mde = next((l / 100 for l in range(5, 301, 5) if sample_size(baseline, l / 100) <= per_arm_available), None)
    ab = {"variants": {"A": copy["sms_a_ar"], "B": copy["sms_b_ar"]}, "channel": "SMS", "metric": "redemption at the merchant within 30 days",
          "baseline_rate": baseline, "alpha": 0.05, "power": 0.8, "audience_opted_in": audience, "holdout_pct": 10,
          "per_arm": per_arm_available, "min_detectable_lift": mde,
          "per_arm_for_20pct_lift": sample_size(baseline, 0.20),
          "guardrails": ["opt-out rate", "complaints about the campaign"],
          "note": ("Two-proportion test at 5% significance and 80% power. With this audience the test can detect a relative lift of "
                   f"{int(mde * 100)}% or more in redemption; smaller effects need a longer test or a wider segment." if mde else
                   "Audience too small for a reliable A/B test: widen the segment or run a single variant.")}
    return {"segment": {**seg, "persona": body.persona, "city": body.city}, "profile": profile, "merchants": merchants, "offer": offer, "copy": copy,
            "compliance": {"passed": not issues, "issues": issues, "initial_issues": first_issues, "auto_fixed": fixed},
            "banner": img, "ab_test": ab, "synthetic": True, "trace": trace.to_list(), "total_ms": trace.total_ms()}


@app.post("/admin/banners")
async def make_banners():
    """Pre-generate one banner per category (requires make image-on) so D3 works when SDXL is off."""
    BANNERS.mkdir(parents=True, exist_ok=True)
    done = []
    async with httpx.AsyncClient(timeout=180) as c:
        for cat, scene in BANNER_SCENE.items():
            prompt = f"commercial banking advertisement photo, {scene}, {PALETTE}, bright, clean, professional, copy space on the right"
            r = (await c.post(f"{SDXL_URL}/generate", json={"prompt": prompt, "steps": 25, "seed": 11})).json()
            (BANNERS / f"{cat}.png").write_bytes(base64.b64decode(r["png_base64"]))
            done.append(cat)
    return {"banners": done}
