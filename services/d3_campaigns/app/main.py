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
from pydantic import BaseModel, Field

from nbe_core import create_app, llm, retrieval, settings
from nbe_core import locale as L
from nbe_core.text import normalize_map, plain_typography
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
# Rules run on nbe_core.text.normalize_map output: no diacritics/kashida/zero-width, أإآ->ا, ة->ه, ى->ي,
# Arabic digits -> 0-9, ٪ -> %, lower case. So patterns are written in that folded form.
DISCLAIMER = {"ar": re.compile(r"(?:تن|ت|ي)طبق\s*(?:ال)?شروط\s*(?:و|&)\s*(?:ال)?احكام"),
              "en": re.compile(r"t\s*&\s*cs?\s+apply|terms\s*(?:and|&)\s*conditions\s+apply")}
_PRE = r"(?<!\w)(?:و|ف)?(?:ب|ل|ك)?(?:ال)?"    # attached conjunction / preposition / article
_MIA = r"(?:مئه|ميه|مائه)"
BANNED = [  # (label, pattern). Conservative: in bank copy "المضمون" reads as "the guaranteed", so it is caught too.
    ("guaranteed", re.compile(_PRE + r"مضمون(?:ه|ين|ات|ان|ا)?(?!\w)")),
    ("guarantee (verb)", re.compile(r"(?<!\w)(?:و|ف)?ب?[نيت]ضمن(?:ون|وا)?(?:لك|لكم|لهم|ها|ه)?(?!\w)")),
    ("guarantee", re.compile(r"guarantee[ds]?|guaranty")),
    ("100%", re.compile(r"(?<![\d.])100\s*(?:%|percent|بال" + _MIA + r"|في\s*ال" + _MIA + r")|" + _MIA + r"\s*(?:%|في\s*ال" + _MIA + r"|بال" + _MIA + r")")),
    ("competitor comparison", re.compile(_PRE + r"افضل\s+من(?!\w)|better\s+than")),
    ("best bank", re.compile(r"(?<!\w)(?:ال)?افضل\s+بنك|البنك\s+الافضل|best\s+bank")),
    ("totally free", re.compile(r"مجان(?:ا|ي|يه)?\s+(?:تماما|بالكامل|100)|(?:totally|completely|100%)\s+free")),
    ("no conditions", re.compile(r"(?:بدون|بلا|من\s+غير)\s+(?:اي\s+)?شروط|no\s+(?:terms|conditions|strings)")),
    ("risk-free", re.compile(r"risk[\s-]*free|(?:بدون|بلا|من\s+غير)\s+(?:اي\s+)?مخاطر")),
]
# SMS parts on a real gateway: GSM-7 = 160 chars (153/part when split); anything else (all Arabic) is UCS-2 = 70 (67/part).
# Arabic gets 2 parts: 1 part (70 chars) cannot hold rate + cap + merchant + date + disclaimer. English stays at 1.
SMS_MAX_PARTS = {"ar": 2, "en": 1}
GSM7 = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")
GSM7_EXT = set("^{}\\[~]|€")
MAX_FIX_PASSES = 2
BASELINE_NOTE = ("Assumption, not measured: the synthetic data has no redemption history, so the A/B plan uses an assumed "
                 "30-day redemption rate for a targeted cashback SMS. Replace it with the bank's historical rate.")
BASELINE_NOTE_AR = ("افتراض غير مقيس: البيانات التجريبية لا تتضمن سجلاً للاستفادة من العروض، لذلك تستخدم خطة A/B معدّل استفادة مفترضاً "
                    "خلال 30 يوماً لرسالة استرداد نقدي موجّهة. استبدله بالمعدّل التاريخي للبنك.")
# run_id -> index of the flow step in progress (0 segment … 5 banner / A-B plan); the portal lights its flow chips from this
PROGRESS: dict[str, int] = {}


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


def interest_profile(conn, persona: str, city: str | None, metric: str = "frequency") -> list[dict]:
    """Category share of the segment's activity versus all customers (lift).

    metric="frequency" ranks by share of transactions: what people buy often. metric="spend" ranks by share of
    money, which over-weights big-ticket categories (one flight outweighs months of coffee); kept for the eval.
    Ranked by share (lift only breaks ties): share × lift over-favours niche categories only this segment buys.
    Penetration is the % of segment customers who bought in the category at least once.
    """
    where, args = "c.persona = %s", [persona]
    if city:
        where += " AND c.city = %s"
        args.append(city)
    measure = {"frequency": "n", "spend": "spend"}[metric]
    return conn.execute(f"""
        WITH seg AS (SELECT m.category, m.category_ar, m.category_en, sum(t.amount) AS spend, count(*) AS n, count(DISTINCT t.customer_id) AS buyers
                     FROM d3.transactions t JOIN d3.customers c ON c.id = t.customer_id JOIN d3.merchants m ON m.id = t.merchant_id
                     WHERE {where} GROUP BY 1, 2, 3),
             base AS (SELECT m.category, sum(t.amount) AS spend, count(*) AS n FROM d3.transactions t JOIN d3.merchants m ON m.id = t.merchant_id GROUP BY 1),
             size AS (SELECT count(*) AS customers FROM d3.customers c WHERE {where})
        SELECT * FROM (
            SELECT seg.category, seg.category_ar, seg.category_en, seg.n AS transactions, round(seg.spend) AS spend,
                   round(100.0 * seg.buyers / size.customers, 1) AS penetration,
                   round(100.0 * seg.{measure} / sum(seg.{measure}) OVER (), 1) AS share,
                   round((seg.{measure}::numeric / sum(seg.{measure}) OVER ()) / (base.{measure}::numeric / sum(base.{measure}) OVER ()), 2) AS lift
            FROM seg JOIN base USING (category) CROSS JOIN size) p
        ORDER BY share DESC, lift DESC""", args + args).fetchall()


@app.get("/eval/profile")
def eval_profile(metric: str = "frequency", min_customers: int = 30):
    """Score the interest profile against the generator's ground truth (persona category weights).

    Per segment (persona, and persona x city): does the top-ranked category match the persona's heaviest
    weight, how many of the true top 3 are in the profile's top 3, and the mean absolute error between the
    profile's transaction share and the expected share. Segments under min_customers are reported separately.
    """
    if metric not in ("frequency", "spend"):
        raise HTTPException(400, "metric must be frequency or spend")
    personas = ground_truth()
    results = []
    with db() as conn:
        segs = conn.execute("SELECT persona, city, count(*) AS n FROM d3.customers GROUP BY ROLLUP (1, 2) HAVING persona IS NOT NULL").fetchall()
        for s in segs:
            weights = personas[s["persona"]]
            total = sum(weights.values())
            truth = sorted(weights, key=weights.get, reverse=True)
            profile = interest_profile(conn, s["persona"], s["city"], metric)
            ranked = [p["category"] for p in profile]
            freq = {p["category"]: p["transactions"] for p in profile}
            n = sum(freq.values()) or 1
            mae = sum(abs(100 * freq.get(c, 0) / n - 100 * weights.get(c, 0) / total) for c in set(freq) | set(weights)) / len(set(freq) | set(weights))
            results.append({"persona": s["persona"], "city": s["city"], "customers": s["n"], "top1_ok": bool(ranked) and ranked[0] == truth[0],
                            "top3_overlap": len(set(ranked[:3]) & set(truth[:3])), "share_mae_pp": round(mae, 2),
                            "predicted_top3": ranked[:3], "true_top3": truth[:3]})

    def summary(rows):
        return {"segments": len(rows), "top1_accuracy": round(sum(r["top1_ok"] for r in rows) / len(rows), 3) if rows else None,
                "top3_recall": round(sum(r["top3_overlap"] for r in rows) / (3 * len(rows)), 3) if rows else None,
                "share_mae_pp": round(sum(r["share_mae_pp"] for r in rows) / len(rows), 2) if rows else None}
    whole = [r for r in results if r["city"] is None]
    cities = [r for r in results if r["city"] is not None and r["customers"] >= min_customers]
    small = [r for r in results if r["city"] is not None and r["customers"] < min_customers]
    return {"metric": metric, "personas": summary(whole), "persona_city": summary(cities), "small_segments": summary(small),
            "persona_detail": whole, "misses": [r for r in cities + small if not r["top1_ok"]]}


def ground_truth() -> dict[str, dict[str, float]]:
    """Persona -> category weights, read from the generator so the eval cannot drift from the data."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("d3_commerce", Path("/data/generators/d3_commerce.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {k: v[2] for k, v in mod.PERSONAS.items()}


class CampaignIn(BaseModel):
    persona: str
    city: str | None = None
    brief: str = ""
    stress_test: bool = False     # plant a non-compliant claim to show the compliance check catching it
    baseline_rate: float = Field(0.08, gt=0, lt=0.5)   # assumed 30-day redemption rate for the A/B sizing (see BASELINE_NOTE)
    run_id: str | None = Field(None, max_length=64)    # set by the portal to follow this run at /campaign/progress/{run_id}


COPY_SCHEMA = {"type": "object", "properties": {k: {"type": "string"} for k in (
    "sms_a_ar", "sms_b_ar", "sms_en", "email_subject_ar", "email_body_ar", "email_subject_en", "email_body_en", "social_local", "banner_headline_ar")},
    "required": ["sms_a_ar", "sms_b_ar", "sms_en", "email_subject_ar", "email_body_ar", "email_subject_en", "email_body_en", "social_local", "banner_headline_ar"]}


def sms_parts(text: str) -> tuple[int, int, str]:
    """(billable characters, SMS parts, encoding) as a gateway would count them."""
    if all(c in GSM7 or c in GSM7_EXT for c in text):
        n, single, multi, enc = len(text) + sum(c in GSM7_EXT for c in text), 160, 153, "GSM-7"
    else:
        n, single, multi, enc = len(text.encode("utf-16-le")) // 2, 70, 67, "UCS-2"
    return n, 1 if n <= single else math.ceil(n / multi), enc


def sms_info(key: str, text: str) -> dict:
    """What the portal shows under an SMS: its billable length against the limit for its language and encoding."""
    n, parts, enc = sms_parts(text)
    max_parts = SMS_MAX_PARTS["en" if key.endswith("_en") else "ar"]
    single, multi = (160, 153) if enc == "GSM-7" else (70, 67)
    return {"chars": n, "parts": parts, "encoding": enc, "max_parts": max_parts, "max_chars": single if max_parts == 1 else max_parts * multi}


def banned_spans(text: str) -> list[tuple[str, int, int]]:
    """(label, start, end) of every banned claim, located in the ORIGINAL text via the normalisation map."""
    norm, idx = normalize_map(text)
    return [(label, idx[m.start()], idx[m.end() - 1] + 1) for label, pat in BANNED for m in pat.finditer(norm)]


FACT_FIELDS = ("sms_a_ar", "sms_b_ar", "sms_en", "email_body_ar", "email_body_en", "social_local")


def missing_facts(key: str, text: str, offer: dict) -> list[str]:
    """Offer terms the message must state: the rate and the cap everywhere, the merchant in Arabic copy.
    Stops a message that is only the disclaimer (or states the wrong rate) from passing."""
    norm = re.sub(r"(?<=\d)[,٬](?=\d{3})", "", normalize_map(text)[0])   # 2,500 -> 2500
    missing = []
    if not re.search(rf"(?<![\d.]){offer['cashback_pct']}\s*%", norm):
        missing.append(f"{offer['cashback_pct']}%")
    if not re.search(rf"(?<![\d.]){offer['cap']}(?![\d.])", norm):
        missing.append(f"cap {offer['cap']}")
    if not key.endswith("_en"):
        core = normalize_map(re.sub(r"\s*التجريبي[ةه]?$", "", offer["merchant"]))[0]
        if core not in norm and " ".join(core.split()[1:] or [core]) not in norm:   # "مطعم ابو شقره" or "ابو شقره"
            missing.append(offer["merchant"])
    return missing


def offer_text(key: str, offer: dict) -> str:
    """Plain, compliant message built from the offer terms alone: used when the model cannot get the facts right."""
    if key.endswith("_en"):
        return f"{offer['cashback_pct']}% cashback up to EGP {offer['cap']} when you pay by card at our partner merchant until {offer['valid_until']}. {REQUIRED['en']}"
    return (f"استرداد نقدي {offer['cashback_pct']}% بحد أقصى {offer['cap']} جنيه عند الدفع ببطاقتك في {offer['merchant']} "
            f"حتى {offer['valid_until']}. {REQUIRED['ar']}")


def tidy(copy: dict) -> dict:
    """Plain hyphens and spaces in every field; the banner headline, drawn over the image, is words only."""
    copy = {k: plain_typography(v) if isinstance(v, str) else v for k, v in copy.items()}
    headline = re.sub(r"(?<=\S)-(?=\S)|[*_#`]", " ", str(copy.get("banner_headline_ar", "")))
    copy["banner_headline_ar"] = re.sub(r"\s+", " ", headline).strip()
    return copy


def compliance(copy: dict, offer: dict | None = None) -> list[dict]:
    issues = []
    for key, text in copy.items():
        lang = "en" if key.endswith("_en") else "ar"
        norm = normalize_map(text)[0]
        if offer and key in FACT_FIELDS and (missing := missing_facts(key, text, offer)):
            issues.append({"field": key, "rule": "offer_terms", "detail": "missing " + ", ".join(missing)})
        if key not in ("banner_headline_ar",) and not key.startswith("email_subject") and not DISCLAIMER[lang].search(norm):
            issues.append({"field": key, "rule": "required_disclaimer", "detail": f"missing «{REQUIRED[lang]}»"})
        if key.startswith("sms"):
            n, parts, enc = sms_parts(text)
            if parts > SMS_MAX_PARTS[lang]:
                issues.append({"field": key, "rule": "sms_length", "detail": f"{n} chars {enc} = {parts} SMS parts (max {SMS_MAX_PARTS[lang]})"})
        for label, s, e in banned_spans(text):
            issues.append({"field": key, "rule": "banned_claim", "detail": f"{label}: «{text[s:e]}»"})
    return issues


def enforce(copy: dict, offer: dict | None = None) -> tuple[dict, list[dict]]:
    """Last line of defence after the model's fix passes: make the copy compliant in code, never ship a banned claim.
    Drops the whole clause holding a banned claim (a half-deleted promise reads worse), appends a missing disclaimer,
    and trims an over-long SMS at a word boundary while keeping the disclaimer. A message that still misses the
    offer terms is replaced by a plain one built from the offer itself."""
    copy, actions = dict(copy), []
    for key, text in copy.items():
        lang = "en" if key.endswith("_en") else "ar"
        if offer and key in FACT_FIELDS and (missing := missing_facts(key, text, offer)):
            text = offer_text(key, offer)
            actions.append({"field": key, "action": "replaced_with_offer_terms", "detail": "missing " + ", ".join(missing)})
        while spans := banned_spans(text):
            label, s, e = spans[0]
            cut = re.compile(r"[.!?؟،,؛;\n]")
            a = max((m.end() for m in cut.finditer(text, 0, s)), default=0)
            b = next((m.end() for m in cut.finditer(text, e)), len(text))
            if DISCLAIMER[lang].search(normalize_map(text[a:b])[0]):   # never drop the disclaimer: cut just the claim
                a, b = s, e
            actions.append({"field": key, "action": "removed_claim", "detail": f"{label}: «{text[a:b].strip()}»"})
            text = re.sub(r"[ \t]{2,}", " ", text[:a] + " " + text[b:]).strip(" ،,")
        needs_disclaimer = key != "banner_headline_ar" and not key.startswith("email_subject")
        if needs_disclaimer and not DISCLAIMER[lang].search(normalize_map(text)[0]):
            text = f"{text.rstrip()} {REQUIRED[lang]}"
            actions.append({"field": key, "action": "added_disclaimer", "detail": REQUIRED[lang]})
        if key.startswith("sms") and sms_parts(text)[1] > SMS_MAX_PARTS[lang]:
            m = DISCLAIMER[lang].search(normalize_map(text)[0])
            idx = normalize_map(text)[1]
            body = (text[:idx[m.start()]] + text[idx[m.end() - 1] + 1:]).strip() if m else text
            words = body.split()
            while words and sms_parts(f"{' '.join(words)}… {REQUIRED[lang]}")[1] > SMS_MAX_PARTS[lang]:
                words.pop()
            text = f"{' '.join(words)}… {REQUIRED[lang]}"
            actions.append({"field": key, "action": "trimmed_sms", "detail": f"{sms_parts(text)[0]} chars"})
        copy[key] = text
    return copy, actions


def sample_size(p1: float, rel_lift: float, alpha_z: float = 1.96, power_z: float = 0.8416) -> int:
    """Two-proportion test, per arm (alpha 0.05 two-sided, power 80%)."""
    p2 = p1 * (1 + rel_lift)
    return math.ceil((alpha_z + power_z) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2)) / (p2 - p1) ** 2)


async def banner(category: str, trace: Trace) -> dict:
    prompt = f"commercial banking advertisement photo, {BANNER_SCENE.get(category, 'a modern bank card at a shop checkout')}, {PALETTE}, bright, clean, professional, copy space on the right"
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


@app.get("/campaign/progress/{run_id}")
def campaign_progress(run_id: str):
    """Flow step a running campaign has reached; null once it has finished (or was never started)."""
    return {"step": PROGRESS.get(run_id)}


@app.post("/campaign")
async def campaign(body: CampaignIn):
    try:
        return await build_campaign(body)
    finally:
        PROGRESS.pop(body.run_id, None)


async def build_campaign(body: CampaignIn):
    def at(step: int) -> None:
        if body.run_id:
            PROGRESS[body.run_id] = step

    trace = Trace()
    at(0)
    with db() as conn:
        seg = conn.execute("""SELECT persona_ar, count(*) AS n, sum(opt_in_sms::int) AS sms, sum(opt_in_email::int) AS email,
                                     round(avg(age)) AS age FROM d3.customers WHERE persona=%s AND (%s::text IS NULL OR city=%s) GROUP BY 1""",
                          (body.persona, body.city, body.city)).fetchone()
        if not seg:
            raise HTTPException(404, "empty segment")
        at(1)
        with trace.step("sql", "Interest profile: category share of transactions vs all customers (lift)") as s:
            profile = interest_profile(conn, body.persona, body.city)
            s["detail"] = profile[:5]
        offer_cats = [p["category"] for p in profile if p["category"] in OFFER][:3]   # categories we have offer rules for
        if not offer_cats:
            raise HTTPException(409, "this segment has no spending in a category with an offer rule")
        at(2)
        with trace.step("sql", "Merchant match: partner merchants where this segment spends most") as s:
            merchants = conn.execute("""SELECT m.id, m.name_ar, m.category, m.category_ar, m.category_en, m.city, round(sum(t.amount)) AS seg_spend, count(DISTINCT t.customer_id) AS seg_customers
                FROM d3.transactions t JOIN d3.customers c ON c.id = t.customer_id JOIN d3.merchants m ON m.id = t.merchant_id
                WHERE c.persona = %s AND (%s::text IS NULL OR c.city = %s) AND m.partner AND m.category = ANY(%s)
                GROUP BY 1, 2, 3, 4, 5, 6 ORDER BY seg_spend DESC LIMIT 3""",
                (body.persona, body.city, body.city, offer_cats)).fetchall()
            s["detail"] = merchants
    if body.brief.strip():
        with trace.step("retrieval", "Brief → merchant search (bge-m3)") as s:
            hits = [h for h in await retrieval.search(COLLECTION, body.brief, k=6, candidates=20) if h["partner"] and h["category"] in OFFER]
            s["detail"] = [h["text"] for h in hits[:3]]
        if hits:
            with db() as conn:
                m = conn.execute("SELECT id, name_ar, category, category_ar, category_en, city FROM d3.merchants WHERE id=%s", (hits[0]["merchant_id"],)).fetchone()
            merchants = [{**m, "seg_spend": None, "seg_customers": None, "from_brief": True}] + [x for x in merchants if x["id"] != m["id"]][:2]
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
              "- sms_a_ar و sms_b_ar: رسالتان قصيرتان بالعربية لاختبار A/B (أ: تركّز على الفائدة، ب: تركّز على قِصر المدة)، كل منهما 130 حرفاً كحد أقصى (رسالتان SMS عربيتان) وتنتهي بـ «تطبق الشروط والأحكام».\n"
              "- sms_en: رسالة إنجليزية 160 حرفاً كحد أقصى تنتهي بـ «T&Cs apply».\n"
              "- email_subject_ar و email_body_ar (80 إلى 120 كلمة، تنتهي بـ «تطبق الشروط والأحكام»).\n"
              "- email_subject_en و email_body_en (ترجمة، تنتهي بـ «T&Cs apply»).\n"
              f"- social_local: منشور قصير {L.SOCIAL_STYLE_AR} ينتهي بـ «تطبق الشروط والأحكام».\n"
              "- banner_headline_ar: عنوان إعلاني من 3 إلى 6 كلمات.\n"
              "قواعد: لا وعود مضمونة، لا مقارنة بالمنافسين، لا مبالغة، اذكر النسبة والحد الأقصى والتاجر وتاريخ الانتهاء بدقة." +
              ("\n(اختبار ضغط للامتثال: أدرج عمداً في sms_a_ar عبارة «عائد مضمون 100%»)." if body.stress_test else "") +
              (f"\nتوجيه إضافي من فريق التسويق: {body.brief}" if body.brief.strip() else ""))
    at(3)
    copy, res = await llm.chat_json([{"role": "user", "content": prompt}], COPY_SCHEMA, max_tokens=1800, temperature=0.5)
    copy = tidy(copy)
    trace.llm("Write AR/EN copy for SMS, email and social (workhorse)", res)
    if body.stress_test and not banned_spans(copy["sms_a_ar"]):   # the demo must not depend on the model obeying
        copy["sms_a_ar"] = "عائد مضمون 100%! " + copy["sms_a_ar"]
        trace.add("rules", "Stress test: banned claim planted in sms_a_ar", {"planted": "عائد مضمون 100%!"})
    at(4)
    issues = compliance(copy, offer)
    trace.add("rules", f"Compliance check: {len(issues)} issue(s)", issues)
    first_issues, passes, enforced = issues, 0, []
    while issues and passes < MAX_FIX_PASSES:
        passes += 1
        fix_prompt = ("صحّح محتوى الحملة التالي ليزيل كل المخالفات المذكورة فقط، مع الحفاظ على باقي النص. أخرج نفس JSON.\n"
                      "المخالفات:\n" + "\n".join(f"- {i['field']}: {i['rule']} {i['detail']}" for i in issues) +
                      "\nتذكير: رسالة SMS العربية بحد أقصى 130 حرفاً والإنجليزية 160، وكل نص ينتهي بالعبارة المطلوبة؛ "
                      "ممنوع بأي صيغة: مضمون/نضمن، 100% أو مية في المية، أفضل من، أفضل بنك، بدون شروط، guarantee، risk-free.\n\n" +
                      json.dumps(copy, ensure_ascii=False))
        copy, res = await llm.chat_json([{"role": "user", "content": fix_prompt}], COPY_SCHEMA, max_tokens=1800, temperature=0)
        copy = tidy(copy)
        trace.llm(f"Fix compliance issues, pass {passes} (workhorse)", res)
        issues = compliance(copy, offer)
        trace.add("rules", f"Compliance re-check {passes}: {len(issues)} issue(s)", issues)
    if issues:   # the model could not clear them: fix in code rather than ship them
        copy, enforced = enforce(copy, offer)
        issues = compliance(copy, offer)
        trace.add("rules", f"Enforced in code: {len(enforced)} change(s); final check {len(issues)} issue(s)", enforced)
    at(5)
    img = await banner(m["category"], trace)

    # A/B design sized to the real audience: 10% holdout, the rest split evenly between A and B.
    audience = seg["sms"]
    baseline = body.baseline_rate                     # an assumption, see BASELINE_NOTE
    per_arm_available = int(audience * 0.9 / 2)
    mde = next((l / 100 for l in range(5, 301, 5) if sample_size(baseline, l / 100) <= per_arm_available), None)
    ab = {"variants": {"A": copy["sms_a_ar"], "B": copy["sms_b_ar"]}, "channel": "SMS", "metric": "redemption at the merchant within 30 days",
          "baseline_rate": baseline, "baseline_source": "assumption", "baseline_note": BASELINE_NOTE,
          "min_detectable_lift_if_baseline": {f"{r:.0%}": next((l / 100 for l in range(5, 301, 5) if sample_size(r, l / 100) <= per_arm_available), None)
                                              for r in (baseline / 2, baseline * 2) if r < 0.5},
          "alpha": 0.05, "power": 0.8, "audience_opted_in": audience, "holdout_pct": 10,
          "per_arm": per_arm_available, "min_detectable_lift": mde,
          "per_arm_for_20pct_lift": sample_size(baseline, 0.20),
          "guardrails": ["opt-out rate", "complaints about the campaign"],
          "note": ("Two-proportion test at 5% significance and 80% power. With this audience the test can detect a relative lift of "
                   f"{int(mde * 100)}% or more in redemption; smaller effects need a longer test or a wider segment." if mde else
                   "Audience too small for a reliable A/B test: widen the segment or run a single variant.")}
    ab |= {"metric_ar": "الاستفادة من العرض لدى التاجر خلال 30 يوماً", "baseline_note_ar": BASELINE_NOTE_AR,
           "note_ar": ("اختبار نسبتين عند مستوى دلالة 5% وقوة 80%. بهذا الجمهور يستطيع الاختبار رصد ارتفاع نسبي في الاستفادة قدره "
                       f"{int(mde * 100)}% أو أكثر؛ الآثار الأصغر تحتاج اختباراً أطول أو شريحة أوسع." if mde else
                       "الجمهور أصغر من أن يسمح باختبار A/B موثوق: وسّع الشريحة أو أرسل نسخة واحدة.")}
    if copy["sms_a_ar"] == copy["sms_b_ar"]:   # e.g. both replaced by the plain offer text in enforce()
        ab["note"] = "Variants A and B are identical after the compliance fixes, so there is nothing to test: regenerate the copy. " + ab["note"]
        ab["note_ar"] = "النسختان A و B متطابقتان بعد تصحيحات الامتثال، فلا يوجد ما يُختبر: أعد توليد النص. " + ab["note_ar"]
    return {"segment": {**seg, "persona": body.persona, "city": body.city}, "profile": profile, "merchants": merchants, "offer": offer, "copy": copy,
            "compliance": {"passed": not issues, "issues": issues, "initial_issues": first_issues, "auto_fixed": bool(first_issues),
                           "fix_passes": passes, "enforced_in_code": enforced},
            "sms": {k: sms_info(k, copy[k]) for k in ("sms_a_ar", "sms_b_ar", "sms_en")},
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
