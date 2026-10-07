"""Author the text corpora once with the on-box workhorse LLM, from the fact sheets in specs.py, and
commit the output under data/seed/ so the demo data is fixed and reproducible.

    docker compose --profile tools run --rm nbe-datagen python -m data.generators.author [d2 d5 d4 d7]

Every generated document is checked for its facts (each value must appear verbatim); a document that
fails is regenerated, up to three attempts. Golden sets are derived from the specs, not from the LLM.
"""
import asyncio
import json
import random
import re
import sys
from pathlib import Path

from nbe_core import llm
from nbe_core import locale as L
from data.generators import specs

SEED_DIR = Path("/repo/data/seed")
GOLDEN_DIR = Path("/repo/data/seed/golden")
SEM = asyncio.Semaphore(4)
FACT_WARNINGS: list[dict] = []   # documents that still miss a fact after 3 attempts (kept, flagged for review)
SYSTEM = (f"أنت كاتب محتوى في إدارة الإجراءات والشؤون القانونية ببنك {L.ADJ_AR}. تكتب بالعربية الفصحى الواضحة والمهنية. "
          "هذه مواد تجريبية لعرض توضيحي. التزم حرفياً بكل القيم المعطاة (الأرقام والمدد والرسوم) ولا تضف أرقاماً أو شروطاً غير مذكورة.")


async def write(prompt: str, required: list[str], max_tokens: int = 2200, system: str = SYSTEM, label: str = "") -> str:
    """Generate text that must contain every string in `required`; retry up to 3 times."""
    missing: list[str] = []
    for attempt in range(1, 4):
        async with SEM:
            res = await llm.chat([{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                                 "workhorse", max_tokens=max_tokens, temperature=0.4 if attempt > 1 else 0.2)
        text = res.text.strip().removeprefix("```markdown").removeprefix("```").removesuffix("```").strip()
        missing = [r for r in required if _norm(r) not in _norm(text)]
        if not missing:
            print(f"  ok   {label} ({res.completion_tokens} tok, {res.tokens_per_s} tok/s)", flush=True)
            return text
        print(f"  retry {label}: missing {missing}", flush=True)
    FACT_WARNINGS.append({"document": label, "missing": missing})
    print(f"  WARN {label}: kept with missing facts {missing}", flush=True)
    return text


def _norm(s: str) -> str:
    """Compare ignoring diacritics, tatweel, alef/ya variants and whitespace."""
    s = re.sub(r"[ً-ْـ]", "", s)
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي").replace("ة", "ه")
    return re.sub(r"\s+", " ", s).strip()


def fact_lines(facts: dict) -> str:
    return "\n".join(f"- {k}: {v}" for k, v in facts.items())


# ------------------------------------------------------------------ D2 procedures
async def d2() -> None:
    out = SEED_DIR / "d2"
    out.mkdir(parents=True, exist_ok=True)
    manifest, tasks = [], []

    async def one(p: dict, version: int, lang: str) -> None:
        facts = dict(p["v1"]) if version == 1 else {**p["v1"], **p["v2"]}
        date = specs.V1_DATE if version == 1 else specs.V2_DATE
        if lang == "ar":
            supersedes = "يحل هذا الإصدار محل الإصدار 1." if version == 2 else ""
            prompt = (f"اكتب وثيقة إجراء عمل داخلية بعنوان \"{p['title_ar']} - الإصدار {version}\" بصيغة Markdown.\n"
                      f"السطر الأول بعد العنوان: \"تاريخ السريان: {date}\". {supersedes}\n"
                      "الأقسام: ## 1. الغرض، ## 2. النطاق، ## 3. الخطوات (مرقمة)، ## 4. الرسوم والمدد، ## 5. المستندات المطلوبة، ## 6. ملاحظات.\n"
                      f"الحقائق التالية يجب أن تُنسخ في النص حرفياً كما هي دون إعادة صياغة:\n{fact_lines(facts)}\n"
                      "الطول: 300 إلى 450 كلمة. لا تذكر أي رسوم أو مدد أخرى.")
            required = list(facts.values()) + [date]
        else:
            prompt = (f"Write an internal bank working procedure in English, Markdown, titled \"{p['title_en']} - Version {version}\".\n"
                      f"First line after the title: \"Effective date: {date}\". " + ("This version supersedes version 1.\n" if version == 2 else "\n") +
                      "Sections: ## 1. Purpose, ## 2. Scope, ## 3. Steps (numbered), ## 4. Fees and timelines, ## 5. Required documents, ## 6. Notes.\n"
                      f"Translate these facts accurately into English and include every one (keep all numbers exactly):\n{fact_lines(facts)}\n"
                      "Length 250-400 words. Do not add any other fees or timelines.")
            required = [date] + sorted({n for v in facts.values() for n in re.findall(r"\d[\d,.]*", v)})
        text = await write(prompt, required, label=f"D2 {p['id']} v{version} {lang}",
                           system=SYSTEM if lang == "ar" else f"You write clear, professional internal procedures for {'an' if L.ADJ_EN[0] in 'AEIOU' else 'a'} {L.ADJ_EN} bank. Demo material. Use only the facts given.")
        fname = f"{p['id']}_v{version}_{lang}.md"
        (out / fname).write_text(text + "\n", encoding="utf-8")
        manifest.append({"file": fname, "procedure": p["id"], "version": version, "lang": lang, "effective": date,
                         "title": p["title_ar"] if lang == "ar" else p["title_en"], "facts": facts})

    for p in specs.PROCEDURES:
        tasks += [one(p, 1, "ar"), one(p, 2, "ar")]
        if p["en"]:
            tasks.append(one(p, 2, "en"))
    await asyncio.gather(*tasks)
    manifest.sort(key=lambda m: m["file"])
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # Golden questions, from the specs: current values of changed facts, version deltas, and unanswerables
    golden = []
    for p in specs.PROCEDURES:
        for key, new in p["v2"].items():
            q = {"procedure": p["id"], "type": "current_value", "question": f"حسب {p['title_ar']} الحالي، ما هو \"{key}\"؟",
                 "expected": new, "source": f"{p['id']}_v2_ar.md"}
            if key in p["v1"]:
                q["previous"] = p["v1"][key]
            golden.append(q)
        golden.append({"procedure": p["id"], "type": "delta", "question": f"ما الذي تغيّر في {p['title_ar']} بين الإصدار 1 والإصدار 2؟",
                       "expected_changes": {k: {"v1": p["v1"].get(k), "v2": v} for k, v in p["v2"].items()}, "source": f"{p['id']}_v2_ar.md"})
    for q in specs.D2_UNANSWERABLE:
        golden.append({"type": "unanswerable", "question": q, "expected": "not_in_documents"})
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    (GOLDEN_DIR / "d2.json").write_text(json.dumps(golden, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"D2: {len(manifest)} documents, {len(golden)} golden questions")


# ------------------------------------------------------------------ D5 template, contracts and rulings
async def d5() -> None:
    out = SEED_DIR / "d5"
    out.mkdir(parents=True, exist_ok=True)
    clause_text: dict[tuple, str] = {}

    async def clause(c: dict, facts: dict, variant: str) -> None:
        prompt = (f"اكتب نص المادة {c['no']} من عقد تمويل شخصي بعنوان \"المادة {c['no']} - {c['title']}\".\n"
                  f"يجب أن يتضمن النص هذه الأحكام حرفياً:\n{fact_lines(facts)}\n"
                  f"اكتب فقرة أو فقرتين قانونيتين (80 إلى 150 كلمة) بصياغة عقود بنكية {L.ADJ_AR}ة. ابدأ بسطر العنوان كما هو. لا تضف أحكاماً أخرى.")
        clause_text[(c["key"], variant)] = await write(prompt, list(facts.values()), max_tokens=700, label=f"D5 clause {c['key']} {variant}")

    tasks = [clause(c, c["facts"], "template") for c in specs.TEMPLATE_CLAUSES]
    by_key = {c["key"]: c for c in specs.TEMPLATE_CLAUSES}
    for k in specs.CONTRACTS:
        for dev in k["deviations"]:
            tasks.append(clause(by_key[dev["clause"]], dev["facts"], k["id"]))
    await asyncio.gather(*tasks)

    header = "# نموذج عقد تمويل شخصي معتمد\n\nنموذج تجريبي لأغراض العرض. ليس عقداً حقيقياً.\n\n"
    (out / "template.md").write_text(header + "\n\n".join(clause_text[(c["key"], "template")] for c in specs.TEMPLATE_CLAUSES) + "\n",
                                     encoding="utf-8")
    manifest = {"template": "template.md", "contracts": [], "rulings": []}
    for k in specs.CONTRACTS:
        devs = {d["clause"]: d for d in k["deviations"]}
        parts = []
        for c in specs.TEMPLATE_CLAUSES:
            if c["key"] in k.get("missing", []):
                continue
            text = clause_text[(c["key"], k["id"] if c["key"] in devs else "template")]
            text = text.replace(specs.PH_BORROWER, k["borrower"]).replace("[المبلغ]", k["amount"]).replace("[عدد الأقساط]", k["installments"])
            parts.append(text)
        body = (f"# عقد تمويل رقم {k['id']}\n\nالمقترض: {k['borrower']} · قيمة التمويل: {k['amount']} · عدد الأقساط: {k['installments']}\n\n"
                "عقد تجريبي لأغراض العرض.\n\n" + "\n\n".join(parts) + "\n")
        (out / f"{k['id']}.md").write_text(body, encoding="utf-8")
        manifest["contracts"].append({"file": f"{k['id']}.md", "borrower": k["borrower"],
                                      "deviations": [{"clause": d["clause"], "title": by_key[d["clause"]]["title"], "severity": d["severity"],
                                                      "why_ar": d["why_ar"], "template_facts": by_key[d["clause"]]["facts"], "contract_facts": d["facts"]}
                                                     for d in k["deviations"]] +
                                                    [{"clause": m, "title": by_key[m]["title"], "severity": "high",
                                                      "why_ar": "المادة محذوفة بالكامل من العقد", "template_facts": by_key[m]["facts"], "contract_facts": None}
                                                     for m in k.get("missing", [])]})

    async def ruling(r: dict) -> None:
        noun, body = getattr(specs, "RULING_NOUN", ("حكم", "المحكمة"))   # Saudi banking disputes: ("قرار", "اللجنة")
        prompt = (f"اكتب {noun}اً افتراضياً كاملاً (700 إلى 1000 كلمة) بصيغة Markdown، لأغراض عرض توضيحي فقط.\n"
                  f"السطر الأول: \"# {noun} افتراضي لأغراض العرض - {r['id']}\" ثم سطر: \"{body}: {r['court']}\".\n"
                  f"موضوع النزاع: {r['topic']}. منطوق الحكم: {r['outcome']}. المبلغ محل النزاع: {r['amount']}.\n"
                  f"الأقسام: ## الوقائع، ## طلبات المدعي، ## دفاع البنك المدعى عليه، ## أسباب ال{noun}، ## المنطوق. "
                  "الأطراف بأسماء خيالية. لا تستشهد بأرقام أحكام حقيقية.")
        text = await write(prompt, [r["outcome"].split(":")[0], r["court"]], max_tokens=2600, label=f"D5 ruling {r['id']}")
        (out / f"{r['id']}.md").write_text(text + "\n", encoding="utf-8")
        manifest["rulings"].append({"file": f"{r['id']}.md", **r})

    await asyncio.gather(*(ruling(r) for r in specs.RULINGS))
    manifest["rulings"].sort(key=lambda r: r["id"])
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    (GOLDEN_DIR / "d5.json").write_text(json.dumps(manifest["contracts"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"D5: template + {len(manifest['contracts'])} contracts + {len(manifest['rulings'])} rulings")


# ------------------------------------------------------------------ D4 knowledge base
async def d4() -> None:
    out = SEED_DIR / "d4"
    out.mkdir(parents=True, exist_ok=True)
    facts = "\n".join(f"- {p['title_ar']}: " + "؛ ".join(f"{k}: {v}" for k, v in {**p['v1'], **p['v2']}.items()) for p in specs.PROCEDURES)
    schema = {"type": "object", "properties": {"question_ar": {"type": "string"}, "answer_ar": {"type": "string"},
                                               "question_en": {"type": "string"}, "answer_en": {"type": "string"}},
              "required": ["question_ar", "answer_ar", "question_en", "answer_en"]}
    articles = []

    async def one(i: int, topic: str) -> None:
        prompt = (f"اكتب مقالة قصيرة لقاعدة معرفة خدمة العملاء عن: \"{topic}\".\n"
                  "أجب بـ JSON: question_ar (سؤال العميل)، answer_ar (إجابة 60 إلى 120 كلمة)، question_en، answer_en (ترجمة دقيقة).\n"
                  "استخدم فقط الحقائق التالية عند ذكر أي رسوم أو حدود أو مدد، ولا تخترع أرقاماً:\n" + facts +
                  "\nإن لم تكن هناك حقيقة مناسبة فأجب بشكل عام دون أرقام. لا تذكر أرقام هواتف.")
        async with SEM:
            data, res = await llm.chat_json([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}], schema,
                                            "workhorse", max_tokens=1200)
        articles.append({"id": f"KB{i:02d}", "topic": topic, **data})
        print(f"  ok   D4 KB{i:02d} ({res.completion_tokens} tok)", flush=True)

    await asyncio.gather(*(one(i, t) for i, t in enumerate(specs.KB_TOPICS, start=1)))
    articles.sort(key=lambda a: a["id"])
    (out / "kb.json").write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"D4: {len(articles)} knowledge-base articles")


# ------------------------------------------------------------------ D7 complaints
async def d7(n: int = 500, batch: int = 10) -> None:
    out = SEED_DIR / "d7"
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(2026)
    grid = []
    for i in range(n):
        topic = rng.choice(list(specs.COMPLAINT_TOPICS))
        severity = 4 if topic == "fraud" and rng.random() < 0.6 else rng.choices([1, 2, 3, 4], [0.15, 0.35, 0.35, 0.15])[0]
        grid.append({"id": f"CMP-{30001 + i}", "topic": topic, "severity": severity,
                     "channel": rng.choices(list(specs.CHANNELS), [0.3, 0.25, 0.25, 0.2])[0],
                     "lang": rng.choices(list(specs.LANGS), [0.45, 0.4, 0.15])[0],
                     "vulnerable": severity == 4 and rng.random() < 0.4})
    schema = {"type": "object", "properties": {"complaints": {"type": "array", "items": {"type": "object",
              "properties": {"n": {"type": "integer"}, "text": {"type": "string"}, "customer_name": {"type": "string"}},
              "required": ["n", "text", "customer_name"]}}}, "required": ["complaints"]}
    results: dict[str, dict] = {}

    async def one(chunk: list[dict]) -> None:
        spec_lines = "\n".join(
            f"{j + 1}. الموضوع: {specs.COMPLAINT_TOPICS[g['topic']]}؛ الخطورة {g['severity']} ({specs.SEVERITY_DESC[g['severity']]})؛ "
            f"القناة: {specs.CHANNELS[g['channel']]}؛ اللغة: {specs.LANGS[g['lang']]}"
            + ("؛ العميل في ظرف إنساني صعب (مرض أو سن متقدم)" if g["vulnerable"] else "") for j, g in enumerate(chunk))
        prompt = (f"اكتب شكاوى عملاء بنك {L.ADJ_AR} واقعية ومتنوعة (تجريبية)، شكوى لكل سطر من المواصفات التالية، بنفس الترتيب.\n"
                  f"كل شكوى من 25 إلى 90 كلمة، بالأسلوب واللغة المحددين، وتذكر تفاصيل ملموسة (مبالغ بال{L.CURRENCY_AR}، تواريخ، أسماء فروع خيالية). "
                  f"لا تذكر أرقام بطاقات كاملة أو أرقام هوية. customer_name اسم {L.ADJ_AR} خيالي.\n" + spec_lines +
                  "\nأجب بـ JSON: {\"complaints\": [{\"n\": رقم السطر, \"text\": ..., \"customer_name\": ...}]}")
        for attempt in (1, 2, 3):
            try:
                async with SEM:
                    data, _ = await llm.chat_json([{"role": "user", "content": prompt}], schema, "workhorse", max_tokens=3000,
                                                  temperature=0.7)
                items = {c["n"]: c for c in data["complaints"]}
                if all(j + 1 in items for j in range(len(chunk))):
                    for j, g in enumerate(chunk):
                        c = items[j + 1]
                        results[g["id"]] = {**g, "text": c["text"].strip(), "customer_name": c["customer_name"],
                                            "sentiment": "neutral" if g["severity"] == 1 else "negative",
                                            "needs_callback": g["severity"] >= 3 or g["vulnerable"]}
                    print(f"  ok   D7 {chunk[0]['id']}..{chunk[-1]['id']}", flush=True)
                    return
            except Exception as exc:  # noqa: BLE001
                print(f"  retry D7 {chunk[0]['id']}: {type(exc).__name__}", flush=True)
        raise RuntimeError(f"D7 batch {chunk[0]['id']} failed")

    await asyncio.gather(*(one(grid[i:i + batch]) for i in range(0, n, batch)))
    rows = [results[g["id"]] for g in grid]
    with open(out / "complaints.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # Demo queue: a realistic mix of severities (4/6/6/4), spread over topics and languages
    qrng, queue, seen_t, seen_l = random.Random(7), [], set(), {}
    for sev, n in {4: 4, 3: 6, 2: 6, 1: 4}.items():
        pool = [r for r in rows if r["severity"] == sev]
        qrng.shuffle(pool)
        pool.sort(key=lambda r: (r["topic"] in seen_t, seen_l.get(r["lang"], 0)))
        for r in pool[:n]:
            queue.append(r["id"])
            seen_t.add(r["topic"])
            seen_l[r["lang"]] = seen_l.get(r["lang"], 0) + 1
    (out / "demo_queue.json").write_text(json.dumps(queue, indent=2), encoding="utf-8")
    print(f"D7: {len(rows)} complaints, demo queue of {len(queue)}")


async def main(which: list[str]) -> None:
    jobs = {"d2": d2, "d5": d5, "d4": d4, "d7": d7}
    await asyncio.gather(*(jobs[w]() for w in which))
    (SEED_DIR / "fact_check.json").write_text(json.dumps(FACT_WARNINGS, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"fact check: {len(FACT_WARNINGS)} document(s) flagged" + (f": {FACT_WARNINGS}" if FACT_WARNINGS else ""))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or ["d2", "d5", "d4", "d7"]))
