"""D6 file-chat test set (test-cases/chat-files-test/questions.json): upload every file the way the portal
does, ask its questions, score the answers and save the run under a label, so each change to file chat
can be shown as before and after.

    python3 tests/d6_files_eval.py run <label>            upload, ask, score; writes results/<label>.json
    python3 tests/d6_files_eval.py compare <before> <after>   side-by-side table of two saved runs
    python3 tests/d6_files_eval.py multi <label> [--old-portal]   several files attached together (multi/multi.json)
    python3 tests/d6_files_eval.py progress <label> [--old]       what the user is told while a file is being read
    python3 tests/d6_files_eval.py evidence <label>               how well a saved run's answers are cited and confirmed
    python3 tests/d6_files_eval.py uploads <label>            the upload-validation cases in bad-uploads/ (no model calls)
    D6_EVAL_PAUSE=5 ...                                   pause between questions (hosted models rate-limit bursts)

Scoring is automatic and strict on facts: every expected group must appear in the answer (digits,
diacritics and letter forms normalised). A question marked `absent` passes only if the assistant says
the file does not contain the answer. Full answers are saved, so a human can overrule the score.
Standard library only; runs on the host against the gateway.
"""
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "test-cases" / "chat-files-test"
BASE = "http://localhost:8200/api/d6"
# D6_EVAL_EVIDENCE=0 asks for answers without numbered passages and citations, to compare the two on the same models
EVIDENCE = {"evidence": os.environ["D6_EVAL_EVIDENCE"] == "1"} if "D6_EVAL_EVIDENCE" in os.environ else {}
PAUSE = float(os.getenv("D6_EVAL_PAUSE", "0"))      # seconds between questions, to stay under a hosted model's rate limit
MIME = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".csv": "text/csv",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
NOT_IN_FILE = re.compile(
    r"none of|neither|no file|no [a-z ]{0,40}(mentioned|stated|specified|given|provided|listed)|not (mentioned|found|stated|specified|provided|included|available|contain|in the|listed|present|appear)"
    r"|does not|doesn't|do not|no (information|mention|data)|cannot find|can't find|could not find|couldn't find|unable to"
    r"|لم (يرد|يذكر|اجد|تذكر|يتم ذكر|يحدد|تحدد|يتضمن|تتضمن)|غير (مذكور|وارد|متوفر|موجود|متاح|محدد)"
    r"|لا (تتوفر|يتوفر|يذكر|تذكر|يوجد|توجد|يتضمن|تتضمن|يحتوي|تحتوي|يحدد|تحدد|يرد|ترد|استطيع|يمكنني)")


def norm(text: str) -> str:
    """Western digits, no diacritics or tatweel, one form for alef / ya / ta-marbuta, lower case."""
    text = unicodedata.normalize("NFKC", text)                       # Arabic presentation forms from PDF text layers
    text = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))
    text = re.sub("[ً-ْـ]", "", text)
    text = re.sub("[\u2010-\u2013\u2212]", "-", text)                # typographic hyphens some models emit
    text = re.sub("[\u00a0\u2007\u2009\u202f]", " ", text)
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي").replace("ة", "ه")
    text = re.sub(r"(?<=\d)[,٬](?=\d{3})", "", text)                       # 1,250,000 -> 1250000
    text = re.sub(r"[()\[\]*«»\"]", "", text)                           # "page (2)", "**page 2**"
    return re.sub(r"\s+", " ", text).lower()


def score(q: dict, answer: str) -> bool:
    a = norm(answer)
    if q.get("absent"):
        return bool(NOT_IN_FILE.search(a))
    # An alternative starting with "re:" is a regular expression (used for bare numbers, so 8 does not match 18)
    return all(any(re.search(alt[3:], a) if alt.startswith("re:") else norm(alt) in a for alt in group) for group in q["expect"])


def call(path: str, data: bytes, content_type: str, timeout: int = 900) -> tuple[dict, float]:
    """One request; a 5xx (the model provider's rate limit surfaces as one) is retried a few times after a pause."""
    for attempt in range(5):
        t = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE + path, data, {"Content-Type": content_type}), timeout=timeout) as r:
                return json.load(r), round(time.time() - t, 1)
        except urllib.error.HTTPError as e:
            out = {"error": f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}"}, round(time.time() - t, 1)
            if e.code < 500 or attempt == 4:
                return out
            time.sleep(25)
        except Exception as e:  # noqa: BLE001 - a timeout or dropped connection is a result too
            return {"error": f"{type(e).__name__}: {e}"}, round(time.time() - t, 1)
    return out


def upload(path: Path, raw: bool = False, lang: str = "en"):
    """Upload one file as the portal does. raw=True returns (status, body, seconds) without retries, for the validation cases."""
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: {MIME.get(path.suffix.lower(), 'application/octet-stream')}\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    if not raw:
        return call("/upload", body, f"multipart/form-data; boundary={boundary}")
    t = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{BASE}/upload?lang={lang}", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}), timeout=600) as r:
            return r.status, json.load(r), round(time.time() - t, 1)
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(text), round(time.time() - t, 1)
        except json.JSONDecodeError:
            return e.code, {"detail": text[:200]}, round(time.time() - t, 1)


def uploads(label: str) -> None:
    """Validation cases (bad-uploads/uploads.json): each file must be refused with the expected status and code, or accepted."""
    folder = ROOT / "bad-uploads"
    cases = json.loads((folder / "uploads.json").read_text(encoding="utf-8"))["cases"]
    rows = []
    for c in cases:
        status, body, secs = upload(folder / c["file"], raw=True)
        detail = body.get("detail")
        code = detail.get("code") if isinstance(detail, dict) else None
        message = (detail.get("message") if isinstance(detail, dict) else detail) or ""
        ok = status == c["status"] and (c["code"] is None or code == c["code"])
        rows.append({**c, "got_status": status, "got_code": code, "message": str(message)[:300], "s": secs, "ok": ok})
        print(f"  {'PASS' if ok else 'FAIL'} {c['file']:32} want {c['status']} {c['code'] or 'accepted':18} got {status} {code or '-':18} {secs:>5}s  {str(message)[:95]}", flush=True)
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / f"{label}.json").write_text(json.dumps({"label": label, "cases": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{label}: {sum(r['ok'] for r in rows)}/{len(rows)} cases as expected; saved results/{label}.json")


def proof(r: dict) -> dict:
    """The citations of an answer, cut down to what the evidence report needs."""
    if "sources" not in r:
        return {}
    return {"sources": [{k: s.get(k) for k in ("label", "file", "page", "where", "status", "missing", "elsewhere", "wrong_page")} for s in r["sources"]],
            "quotes": r.get("quotes", []), "loose": (r.get("evidence") or {}).get("figures_not_in_files", [])}


def evidence_report(label: str) -> None:
    """How well a saved run's answers are backed: cited at all, cited to the right page, figures confirmed."""
    run_ = json.loads((ROOT / "results" / f"{label}.json").read_text(encoding="utf-8"))
    spec = {q["id"]: q for f in json.loads((ROOT / "questions.json").read_text(encoding="utf-8"))["files"] for q in f["questions"]}
    spec.update({q["id"]: q for st in json.loads((ROOT / "multi" / "multi.json").read_text(encoding="utf-8"))["sets"] for q in st["questions"]})
    qs = [q for f in run_["files"] for q in f["questions"] if q["id"] in spec and q.get("answer")]
    in_file = [q for q in qs if not spec[q["id"]].get("absent")]
    cited = [q for q in in_file if q.get("sources")]
    paged = [q for q in cited if spec[q["id"]].get("page") and any(s.get("where", "").startswith("Page") for s in q["sources"])]
    right_page = [q for q in paged if any(s["page"] == spec[q["id"]]["page"] for s in q["sources"])]
    sources = [s for q in qs for s in q.get("sources", [])]
    by = lambda st: sum(s["status"] == st for s in sources)  # noqa: E731
    absent = [q for q in qs if spec[q["id"]].get("absent")]
    quotes_ = [x for q in qs for x in q.get("quotes", [])]
    pct = lambda a, b: f"{len(a) if not isinstance(a, int) else a}/{len(b) if not isinstance(b, int) else b}"  # noqa: E731
    print(f"{label}")
    print(f"  answers correct                              {sum(q['ok'] for q in qs)}/{len(qs)}")
    print(f"  answers with at least one citation           {pct(cited, in_file)}   (questions whose answer is in the file)")
    print(f"  cited to the expected page                   {pct(right_page, paged)}   (questions with a known page)")
    print(f"  cited passages: figures confirmed            {by('verified')}/{len(sources)}")
    print(f"                  figures in the file, other passage {by('nearby')}/{len(sources)}")
    print(f"                  wording confirmed            {by('supported')}/{len(sources)}")
    print(f"                  not checkable                {by('unchecked')}/{len(sources)}")
    print(f"                  flagged to check             {by('check')}/{len(sources)}")
    print(f"  quotes found word for word                   {sum(x['found'] for x in quotes_)}/{len(quotes_)}")
    print(f"  'not in the file' answers that cite nothing  {sum(not q.get('sources') for q in absent)}/{len(absent)}")
    loose = [q for q in qs if q.get("loose")]
    print(f"  answers with a figure that is not in the files {len(loose)}/{len(qs)}   (of which wrong answers: {sum(not q['ok'] for q in loose)})")
    for q in loose[:12]:
        print(f"    figure      {q['id']} ({'right' if q['ok'] else 'WRONG'} answer): {q['loose']}  | {q['answer'][:70]!r}")
    wrong_page = [q for q in paged if q not in right_page]
    for q in wrong_page[:8]:
        print(f"    wrong page  {q['id']}: expected {spec[q['id']]['page']}, cited {[s['page'] for s in q['sources']]}")
    for q in [q for q in qs if any(s['status'] == 'check' for s in q.get('sources', []))][:12]:
        why = [("page " + str(s.get("wrong_page")) if s.get("wrong_page") else str(s["missing"]) + (" (elsewhere: " + str(s.get("elsewhere")) + ")" if s.get("elsewhere") else " (nowhere)")) for s in q["sources"] if s["status"] == "check"]
        print(f"    to check    {q['id']} ({'right' if q['ok'] else 'WRONG'} answer): {why}  | {q['answer'][:60]!r}")


def run(label: str) -> None:
    spec = json.loads((ROOT / "questions.json").read_text(encoding="utf-8"))
    out = {"label": label, "started": time.strftime("%Y-%m-%d %H:%M"), "files": []}
    for f in spec["files"]:
        up, secs = upload(ROOT / f["file"])
        entry = {"file": f["file"], "kind": f["kind"], "upload_s": secs, "upload_error": up.get("error"),
                 "chars": up.get("chars"), "pages": up.get("pages"), "converted_by": up.get("converted_by"),
                 "preview": (up.get("preview") or "")[:300], "questions": []}
        print(f"\n== {f['file']}: {entry['upload_error'] or str(entry['chars']) + ' chars, ' + str(entry['converted_by'])} ({secs}s)", flush=True)
        for q in f["questions"]:
            time.sleep(PAUSE)
            if up.get("error"):
                res = {"id": q["id"], "q": q["q"], "expected": q["answer"], "answer": "", "ok": False, "error": "upload failed", "s": 0}
            else:
                r, s = call("/chat", json.dumps({"messages": [{"role": "user", "content": q["q"]}], "file_id": up["file_id"], **EVIDENCE}).encode(), "application/json")
                ans = r.get("answer", "")
                res = {"id": q["id"], "q": q["q"], "expected": q["answer"], "answer": ans, "ok": score(q, ans) if ans else False,
                       "error": r.get("error"), "s": s, "model": (r.get("route") or {}).get("model"), **proof(r)}
            entry["questions"].append(res)
            print(f"  {'PASS' if res['ok'] else 'FAIL'} {q['id']:8} {res['s']:>5}s  {(res['error'] or res['answer'])[:90]!r}", flush=True)
        out["files"].append(entry)
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / f"{label}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    total = [q["ok"] for f in out["files"] for q in f["questions"]]
    print(f"\n{label}: {sum(total)}/{len(total)} passed; saved results/{label}.json")


def multi(label: str, old_portal: bool) -> None:
    """Multi-file sets (multi/multi.json): attach every file of a set, then ask. --old-portal emulates the portal that
    kept one file at a time: each new attachment replaced the one before, so only the last file reaches the chat."""
    sets = json.loads((ROOT / "multi" / "multi.json").read_text(encoding="utf-8"))["sets"]
    out = {"label": label, "mode": "old portal (last file only)" if old_portal else "all files", "files": []}
    for st in sets:
        ups = [upload(ROOT / f)[0] for f in st["files"]]
        ids = [u["file_id"] for u in ups if "file_id" in u]
        entry = {"file": f"[set] {st['set']}", "kind": st["about"], "upload_s": 0, "upload_error": None,
                 "chars": sum(u.get("chars", 0) for u in ups), "pages": None, "converted_by": f"{len(ids)} files", "questions": []}
        print(f"\n== {st['set']}: {', '.join(st['files'])}", flush=True)
        for q in st["questions"]:
            time.sleep(PAUSE)
            body = {"messages": [{"role": "user", "content": q["q"]}], **({"file_id": ids[-1]} if old_portal else {"file_ids": ids})}
            r, secs = call("/chat", json.dumps(body).encode(), "application/json")
            ans = r.get("answer", "")
            # A cited passage names its file on the chip under the answer: that counts as naming the file
            named = " ".join(f"({s['file']})" for s in r.get("sources", []))
            res = {"id": q["id"], "q": q["q"], "expected": q["answer"], "answer": ans, "ok": score(q, f"{ans} {named}") if ans else False,
                   "named": named, "error": r.get("error"), "s": secs, "model": (r.get("route") or {}).get("model"), **proof(r)}
            entry["questions"].append(res)
            print(f"  {'PASS' if res['ok'] else 'FAIL'} {q['id']:9} {secs:>5}s  {(res['error'] or ans)[:110]!r}", flush=True)
        out["files"].append(entry)
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / f"{label}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    total = [q["ok"] for f in out["files"] for q in f["questions"]]
    print(f"\n{label}: {sum(total)}/{len(total)} passed; saved results/{label}.json")


PROGRESS_FILES = ["scanned_10_pages.pdf", "test_cirular.pdf", "mixed_text_scan.pdf", "banking_compare.png", "Reg_circular.pdf", "branch_loans.xlsx"]


def progress(label: str, old: bool) -> None:
    """What the user is told while a file is being read. --old uses the one blocking /upload call: nothing until it ends.
    Otherwise the upload is started as a job and its status is polled twice a second, as the portal does."""
    def start(path: Path) -> tuple[int, dict, float]:
        boundary = uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        t = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{BASE}/upload/start", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}), timeout=60) as r:
                return r.status, json.load(r), round(time.time() - t, 2)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), round(time.time() - t, 2)

    rows = []
    for name in PROGRESS_FILES:
        path, t0 = ROOT / name, time.time()
        if old:
            status, body, total = upload(path, raw=True)
            row = {"file": name, "first_feedback_s": total, "total_s": total, "updates": 0, "stages": [], "pages": None, "ok": status == 200}
        else:
            status, job, first = start(path)
            seen, pages, final = [], [], {}
            while status == 200 and time.time() - t0 < 600:
                with urllib.request.urlopen(f"{BASE}/upload/{job['job_id']}/status", timeout=30) as r:
                    st = json.load(r)
                snap = (st["stage"], st.get("pages_done"), st.get("pages_total"))
                if not seen or seen[-1] != snap:
                    seen.append(snap)
                    if st.get("pages_total"):
                        pages.append(st["pages_done"])
                if st["stage"] in ("done", "failed", "cancelled"):
                    final = st
                    break
                time.sleep(0.5)
            stages = list(dict.fromkeys(s[0] for s in seen))
            row = {"file": name, "first_feedback_s": first, "total_s": round(time.time() - t0, 1), "updates": len(seen), "stages": stages,
                   "pages": f"{pages[-1]}/{seen[-1][2]}" if pages else None, "counts_up": pages == sorted(pages),
                   "ok": final.get("stage") == "done" and bool((final.get("result") or {}).get("file_id"))}
        rows.append(row)
        print(f"  {name:24} first feedback {row['first_feedback_s']:>5}s  total {row['total_s']:>5}s  updates {row['updates']:>2}  "
              f"pages {row['pages'] or '-':>5}  {' > '.join(row['stages']) or '(no feedback until the end)'}  {'OK' if row['ok'] else 'FAILED'}", flush=True)
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / f"{label}.json").write_text(json.dumps({"label": label, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")


def compare(a: str, b: str) -> None:
    A, B = (json.loads((ROOT / "results" / f"{x}.json").read_text(encoding="utf-8")) for x in (a, b))
    fb = {f["file"]: f for f in B["files"]}
    spec = {q["id"]: q for f in json.loads((ROOT / "questions.json").read_text(encoding="utf-8"))["files"] for q in f["questions"]}
    spec.update({q["id"]: {**q, "topic": "multi-file"} for st in json.loads((ROOT / "multi" / "multi.json").read_text(encoding="utf-8"))["sets"]
                 for q in st["questions"]})
    ta = tb = n = 0
    for f in A["files"]:
        g = fb.get(f["file"])
        if not g:
            continue
        for side in (f, g):          # re-score the saved answers, so a scoring fix applies to old runs too
            for q in side["questions"]:
                q["ok"] = bool(q["answer"]) and score(spec[q["id"]], f"{q['answer']} {q.get('named', '')}")
        pa, pb = sum(q["ok"] for q in f["questions"]), sum(q["ok"] for q in g["questions"])
        ta, tb, n = ta + pa, tb + pb, n + len(f["questions"])
        print(f"\n{f['file']}  ({f['kind']})")
        print(f"  read:   {a}: {f['upload_error'] or f'{f['chars']} chars, {f['converted_by']}, {f['upload_s']}s'}")
        print(f"          {b}: {g['upload_error'] or f'{g['chars']} chars, {g['converted_by']}, {g['upload_s']}s'}")
        print(f"  score:  {pa}/{len(f['questions'])} -> {pb}/{len(g['questions'])}")
        gq = {q["id"]: q for q in g["questions"]}
        for q in f["questions"]:
            r = gq.get(q["id"])
            if r and q["ok"] != r["ok"]:
                print(f"    {q['id']}: {'PASS' if q['ok'] else 'FAIL'} -> {'PASS' if r['ok'] else 'FAIL'}  ({q['q'][:60]})")
    print(f"\nTOTAL  {a}: {ta}/{n}   {b}: {tb}/{n}")
    topics: dict[str, list[int]] = {}          # the same totals split by what each question tests
    for f in A["files"]:
        gq = {q["id"]: q for q in fb.get(f["file"], {"questions": []})["questions"]}
        for q in f["questions"]:
            if q["id"] in gq:
                t = topics.setdefault(spec[q["id"]].get("topic", "content"), [0, 0, 0])
                t[0], t[1], t[2] = t[0] + q["ok"], t[1] + gq[q["id"]]["ok"], t[2] + 1
    for name, (x, y, m) in topics.items():
        print(f"  {name:10} {x}/{m} -> {y}/{m}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "evidence":
        evidence_report(sys.argv[2])
    elif len(sys.argv) >= 3 and sys.argv[1] == "progress":
        progress(sys.argv[2], "--old" in sys.argv)
    elif len(sys.argv) >= 3 and sys.argv[1] == "multi":
        multi(sys.argv[2], "--old-portal" in sys.argv)
    elif len(sys.argv) == 3 and sys.argv[1] == "uploads":
        uploads(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == "run":
        run(sys.argv[2])
    elif len(sys.argv) == 4 and sys.argv[1] == "compare":
        compare(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
