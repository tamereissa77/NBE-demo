"""D6 drafting cases (test-cases/drafting/cases.json): ask for each draft, then judge it with checks computed here,
independently of the service, so a run before a change and a run after it are judged the same way.

    python3 tests/d6_drafting_eval.py run <label>
    python3 tests/d6_drafting_eval.py compare <before> <after>

Standard library only; runs on the host against the gateway.
"""
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
from d6_files_eval import score, upload  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "test-cases" / "drafting"
BASE = "http://localhost:8200/api/d6"
TODAY = datetime.now(ZoneInfo("Africa/Cairo")).date()
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAYS_AR = {"الاثنين": 0, "الإثنين": 0, "الثلاثاء": 1, "الأربعاء": 2, "الاربعاء": 2, "الخميس": 3, "الجمعة": 4, "السبت": 5, "الأحد": 6, "الاحد": 6}
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
MONTHS_AR = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def target(phrase: str) -> date:
    """'tomorrow' or 'next <weekday>': the first such day after today."""
    if phrase == "tomorrow":
        return TODAY + timedelta(days=1)
    want = DAYS.index(phrase.split()[-1])
    return TODAY + timedelta(days=(want - TODAY.weekday() - 1) % 7 + 1)


def plain(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(DIGITS)
    text = re.sub("[ً-ْـ]", "", text).replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = re.sub("[‐-―]", "-", text).replace(" ", " ").replace(" ", " ")
    return re.sub(r"(?<=\d)[,٬](?=\d{3})", "", text).lower()


def has_date(draft: str, d: date) -> bool:
    """The day and month of `d` written together, in English or Arabic, in either order."""
    t = plain(draft)
    month = f"(?:{MONTHS[d.month - 1]}|{MONTHS[d.month - 1][:3]}\\.?|{plain(MONTHS_AR[d.month - 1])}|0?{d.month})"
    return bool(re.search(rf"(?<!\d)0?{d.day}(?:st|nd|rd|th)?[\s/.-]+(?:of\s+)?{month}\b|{month}[\s/.-]+0?{d.day}(?!\d)", t))


def weekday_errors(draft: str) -> list[str]:
    """Every "<weekday> ... <day> <month> [<year>]" in the draft whose weekday does not match the calendar."""
    t, out = plain(draft), []
    names = {**{n: i for i, n in enumerate(DAYS)}, **{plain(k): v for k, v in DAYS_AR.items()}}
    months = {**{m: i + 1 for i, m in enumerate(MONTHS)}, **{plain(m): i + 1 for i, m in enumerate(MONTHS_AR)}}
    wd, mo = "|".join(map(re.escape, names)), "|".join(map(re.escape, months))
    for m in re.finditer(rf"({wd})\W{{0,25}}?(?:the\s+|الموافق\s+|بتاريخ\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({mo})(?:\W+(\d{{4}}))?"
                         rf"|({wd})\W{{0,25}}?({mo})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\W+(\d{{4}}))?", t):
        w, dnum, mname, year = (m.group(1), m.group(2), m.group(3), m.group(4)) if m.group(1) else (m.group(5), m.group(7), m.group(6), m.group(8))
        try:
            d = date(int(year) if year else TODAY.year, months[mname], int(dnum))
        except ValueError:
            out.append(m.group(0))
            continue
        if not year and d < TODAY - timedelta(days=30):
            d = d.replace(year=d.year + 1)
        if d.weekday() != names[w]:
            out.append(f"{m.group(0)!r} is a {DAYS[d.weekday()]}")
    return out


def invented(draft: str, allowed: str) -> list[str]:
    """Numbers of two or more digits in the draft that are in none of: the request, the files, the bank's facts.
    Dates are judged separately (has_date, weekday_errors), so day numbers next to a month and years are skipped."""
    t, ok = plain(draft), plain(allowed)
    mo = "|".join(MONTHS + [m[:3] for m in MONTHS] + [plain(m) for m in MONTHS_AR])
    t = re.sub(rf"\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{mo})\b(?:\W+\d{{4}})?|(?:{mo})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:\W+\d{{4}})?", " ", t)
    t = re.sub(r"\[s\d+\]|\b(?:19|20)\d{2}\b|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}", " ", t)
    out = []
    for n in re.findall(r"\d+(?:\.\d+)?", t):
        core = n.lstrip("0") or "0"
        if len(core) < 2:
            continue
        variants = {core, n} | ({str(int(core) - 12)} if core.isdigit() and 13 <= int(core) <= 23 else set())      # 13:00 for "1 pm"
        if not any(re.search(rf"(?<![\d.]){re.escape(v)}(?!\d|\.\d)", ok) for v in variants):
            out.append(n)
    return list(dict.fromkeys(out))


def placeholders(draft: str) -> list[str]:
    return [p for p in re.findall(r"\[([^\[\]\n]{2,60})\]", draft) if not re.fullmatch(r"S\d+|Page \d+|Sheet: .*", p.strip())]


def post(body: dict) -> dict:
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE + "/chat", json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=600) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == 3:
                return {"error": f"HTTP {e.code}"}
            time.sleep(25)
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}"}
    return {}


def judge(c: dict, r: dict, allowed: str, facts: dict) -> dict:
    draft, chk, route = r.get("answer") or "", c["check"], r.get("route") or {}
    out = {"task": route.get("task") == chk["task"]}
    if "must" in chk:
        out["facts kept"] = bool(draft) and score({"expect": chk["must"]}, draft)
    if "date_of" in chk:
        out["right date"] = has_date(draft, target(chk["date_of"]))
    out["weekdays match"] = bool(draft) and not weekday_errors(draft)
    out["nothing invented"] = bool(draft) and not invented(draft, allowed + " " + " ".join(facts.values()))
    if chk.get("placeholder"):
        out["placeholder used"] = bool(placeholders(draft))
    if chk.get("from_file"):
        out["cites the file"] = bool(r.get("sources") or (r.get("draft") or {}).get("sources"))
    # A draft is expected in the language of its request, unless the case says otherwise
    want = chk.get("lang") or ("ar" if len(re.findall(r"[\u0600-\u06ff]", c["q"])) > len(re.findall(r"[A-Za-z]", c["q"])) else "en")
    ar = len(re.findall(r"[\u0600-\u06ff]", draft))
    if (c.get("options") or {}).get("language") in ("ar", "en"):
        want = c["options"]["language"]
    out["language"] = bool(draft) and (ar > len(re.findall(r"[A-Za-z]", draft))) == (want == "ar")
    words = len(re.findall(r"\S+", re.sub(r"(?im)^\s*\**(subject|الموضوع)\**\s*:.*$", "", draft)))
    if "max_words" in chk:
        out["length"] = 0 < words <= chk["max_words"]
    if "min_words" in chk:
        out["length"] = words >= chk["min_words"]
    shape = chk.get("shape")
    if shape == "memo":
        out["form"] = all(re.search(rf"(?im)^\W*{h}\W*:", draft) for h in ("to", "from", "date", "subject")) or \
            all(re.search(rf"(?m)^\W*{h}\W*:", draft) for h in ("إلى", "من", "التاريخ", "الموضوع"))
    elif shape == "sms":
        out["form"] = 0 < len(draft.strip()) <= 160 and not re.search(r"(?im)^\W*(subject|الموضوع)\W*:", draft)
    elif shape == "subject":
        out["form"] = bool(re.match(r"\W*(subject|الموضوع)\W*:", draft.strip(), re.I))
    if chk.get("lang") == "both":
        out["language"] = len(re.findall(r"[\u0600-\u06ff]", draft)) >= 60 and len(re.findall(r"[A-Za-z]", draft)) >= 60
    if chk.get("no_secret"):
        out["policy"] = bool(draft) and not re.search(
            r"(send|share|provide|confirm|give|tell|reply with|enter)\s+(us\s+)?(with\s+)?(your\s+|his\s+)?(card number|pin|otp|password|cvv)"
            r"|(card number|pin)[^.\n]{0,40}\b(to us|by (e-?mail|reply))", draft, re.I)
    if chk.get("no_promise"):
        out["policy"] = bool(draft) and not re.search(r"\bguarantee|we promise|will be refunded|we will refund|will be compensated|will be reversed|will be credited", draft, re.I)
    if chk.get("requested_promise"):
        report = r.get("draft") or {}
        out["policy"] = "guarantee" in draft.lower() and any(p.get("requested") for p in report.get("policy", []))
    if "small_change" in chk:
        import difflib
        a, b = (r.get("_first") or "").split(), draft.split()
        changed = sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if op != "equal")
        out["revision keeps the rest"] = bool(a) and bool(b) and changed / max(len(a), len(b)) <= chk["small_change"]
    if chk.get("flow"):
        out["working life of a draft"] = bool(r.get("_flow"))
    out["one version"] = bool(draft) and not re.search(r"\b(option|version|alternative)\s*(1|2|one|two|a|b)\b|الخيار\s+(الأول|الثاني|1|2)|النسخة\s+(الأولى|الثانية)", draft, re.I)
    return out


def run(label: str) -> None:
    spec = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    rows = []
    print(f"today is {TODAY:%A %d %B %Y}")
    for c in spec["cases"]:
        ids, texts = [], []
        for f in c.get("files", []):
            up, _ = upload((ROOT / f).resolve())
            ids.append(up.get("file_id"))
            texts.append(json.dumps(up, ensure_ascii=False))
        allowed = c["q"] + " " + c.get("then", "")
        for f in c.get("files", []):                 # a draft may take figures from the attached files
            allowed += " " + _file_text((ROOT / f).resolve())
        allowed += " " + c.get("file_figures", "")
        body = {"messages": [{"role": "user", "content": c["q"]}], "file_ids": [i for i in ids if i], "draft_options": c.get("options", {})}
        t = time.time()
        if c.get("turns"):
            conv = post_conv()
            first = post({**body, **conv})
            r = post({"messages": [{"role": "user", "content": c["then"]}] if conv else
                      [body["messages"][0], {"role": "assistant", "content": first.get("answer", "")}, {"role": "user", "content": c["then"]}], **conv})
            r["_first"] = first.get("answer", "")
        elif c.get("flow"):
            conv = post_conv()
            r = post({**body, **conv})
            r["_flow"] = flow(conv.get("conversation_id"), r.get("answer", ""))
        else:
            r = post(body)
        verdict = judge(c, r, allowed, spec["known_facts"])
        draft = r.get("answer") or ""
        row = {"id": c["id"], "q": c["q"], "draft": draft, "error": r.get("error"), "s": round(time.time() - t, 1), "checks": verdict, "ok": all(verdict.values()),
               "invented": invented(draft, allowed + " " + " ".join(spec["known_facts"].values())), "weekday_errors": weekday_errors(draft),
               "placeholders": placeholders(draft), "model": (r.get("route") or {}).get("model"), "service_report": r.get("draft")}
        rows.append(row)
        bad = [k for k, v in verdict.items() if not v]
        print(f"  {'PASS' if row['ok'] else 'FAIL'} {c['id']:20} {row['s']:>5}s  {('failed: ' + ', '.join(bad)) if bad else ''}"
              + (f"  invented={row['invented']}" if row["invented"] else "") + (f"  {row['weekday_errors']}" if row["weekday_errors"] else ""), flush=True)
        time.sleep(2)
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / f"{label}.json").write_text(json.dumps({"label": label, "today": str(TODAY), "cases": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    checks = [v for r in rows for v in r["checks"].values()]
    print(f"\n{label}: {sum(r['ok'] for r in rows)}/{len(rows)} drafts pass every check; {sum(checks)}/{len(checks)} individual checks pass")


def _file_text(path: Path) -> str:
    """The figures a draft may take from a test file. Spreadsheets are read here; for a PDF the case lists them
    (`file_figures`), since the test has no reader of its own for scans."""
    if path.suffix == ".csv":
        return path.read_text(encoding="utf-8-sig")
    if path.suffix == ".xlsx":
        import zipfile
        with zipfile.ZipFile(path) as z:
            return " ".join(re.sub(r"<[^>]+>", " ", z.read(n).decode("utf-8", "replace")) for n in z.namelist() if n.endswith(".xml"))
    return ""


def api(method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    req = urllib.request.Request(BASE + path, json.dumps(body).encode() if body is not None else None, {"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
            return r.status, json.loads(raw) if "json" in r.headers.get("content-type", "") else raw
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception:  # noqa: BLE001
        return 0, {}


def flow(cid: str | None, draft: str) -> bool:
    """Approval refused while a placeholder is open; the employee fills it in; approval accepted and written to the
    audit log; the versions and the Word file are there."""
    if not cid or "[" not in draft:
        return False
    refused, _ = api("POST", "/draft/approve", {"conversation_id": cid})
    saved, s2 = api("POST", "/draft/save", {"conversation_id": cid, "text": re.sub(r"\[[^\]\n]+\]", "Mr. Ahmed Saad", draft)})
    approved, a = api("POST", "/draft/approve", {"conversation_id": cid, "by": "test-reviewer"})
    _, v = api("GET", f"/draft/{cid}/versions")
    code, docx = api("GET", f"/draft/{cid}/export.docx")
    steps = {"refused with a placeholder open": refused == 409, "edit saved as a new version": saved == 200 and (s2.get("draft") or {}).get("by") == "employee",
             "approved": approved == 200 and bool((a.get("draft") or {}).get("approved")), "two versions kept": len((v or {}).get("versions", [])) >= 2,
             "Word file": code == 200 and isinstance(docx, bytes) and docx[:2] == b"PK"}
    print("        ", {k: v for k, v in steps.items()})
    return all(steps.values())


def post_conv() -> dict:
    try:
        with urllib.request.urlopen(urllib.request.Request(BASE + "/conversation", b"{}", {"Content-Type": "application/json"}), timeout=30) as r:
            return {"conversation_id": json.load(r)["conversation_id"]}
    except Exception:  # noqa: BLE001 - the service before conversations existed
        return {}


def compare(a: str, b: str) -> None:
    A, B = (json.loads((ROOT / "results" / f"{x}.json").read_text(encoding="utf-8")) for x in (a, b))
    rb = {r["id"]: r for r in B["cases"]}
    names: dict[str, list[int]] = {}
    for r in A["cases"]:
        q = rb.get(r["id"])
        if not q:
            continue
        fa, fb = [k for k, v in r["checks"].items() if not v], [k for k, v in q["checks"].items() if not v]
        print(f"{r['id']:20} {'PASS' if r['ok'] else 'FAIL'} -> {'PASS' if q['ok'] else 'FAIL'}   before: {', '.join(fa) or 'all good'}   after: {', '.join(fb) or 'all good'}")
        for k in r["checks"]:
            x = names.setdefault(k, [0, 0, 0])
            x[0], x[1], x[2] = x[0] + r["checks"][k], x[1] + q["checks"].get(k, False), x[2] + 1
    print()
    for k, (x, y, n) in names.items():
        print(f"  {k:18} {x}/{n} -> {y}/{n}")
    print(f"  {'drafts fully right':18} {sum(r['ok'] for r in A['cases'])}/{len(A['cases'])} -> {sum(r['ok'] for r in B['cases'])}/{len(B['cases'])}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "run":
        run(sys.argv[2])
    elif len(sys.argv) == 4 and sys.argv[1] == "compare":
        compare(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
