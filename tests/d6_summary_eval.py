"""D6 summary cases (test-cases/summaries/cases.json, mostly Arabic): ask for each summary, then judge it with
checks computed here, independently of the service, so a run before a change and a run after are judged alike.

    python3 tests/d6_summary_eval.py run <label>
    python3 tests/d6_summary_eval.py compare <before> <after>

A case either pastes its text into the message (`paste`) or attaches files (`files`). Long documents are left
out on purpose: summarising in sections is not exercised here. Standard library only; runs on the host.
"""
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from d6_files_eval import score, upload  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "test-cases" / "summaries"
BASE = "http://localhost:8200/api/d6"
D5_CONTRACT = REPO / "data" / "seed" / "d5" / "C01.md"
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def plain(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(DIGITS)
    text = re.sub("[ً-ْـ]", "", text).replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
    text = re.sub("[‐-―]", "-", text).replace(" ", " ").replace(" ", " ")
    return re.sub(r"(?<=\d)[,٬](?=\d{3})", "", text).lower()


def invented(summary: str, source: str) -> list[str]:
    """Numbers of two or more digits in the summary that are not in the source. Citation marks and page numbers do not count."""
    t = re.sub(r"\[s\d+\]|\[page \d+\]|\b(?:page|صفحه|الصفحه)\s*\d+", " ", plain(summary))
    ok = plain(source)
    out = []
    for n in re.findall(r"\d+(?:\.\d+)?", t):
        core = n.lstrip("0") or "0"
        if len(core) >= 2 and not re.search(rf"(?<![\d.]){re.escape(core)}(?!\d|\.\d)", ok) and not re.search(rf"(?<![\d.]){re.escape(n)}(?!\d|\.\d)", ok):
            out.append(n)
    return list(dict.fromkeys(out))


def body_of(answer: str) -> str:
    return re.sub(r"\[S\d+\]", "", answer)


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
            return {"error": type(e).__name__}
    return {}


def conversation() -> dict:
    try:
        with urllib.request.urlopen(urllib.request.Request(BASE + "/conversation", b"{}", {"Content-Type": "application/json"}), timeout=30) as r:
            return {"conversation_id": json.load(r)["conversation_id"]}
    except Exception:  # noqa: BLE001
        return {}


def judge(c: dict, r: dict, source: str, first: str = "") -> dict:
    chk, route = c["check"], r.get("route") or {}
    text = body_of(r.get("answer") or "")
    out: dict[str, bool] = {}
    if chk.get("asks"):
        out["asks for the document"] = bool(text) and bool(re.search(r"[?؟]|يرجى|برجاء|please provide|الرجاء|الصق|أرفق|paste|attach", text)) and len(text.split()) < 90
        return out
    out["recognised as a summary"] = route.get("task") == "summarise"
    if "must" in chk:
        out["key facts kept"] = bool(text) and score({"expect": chk["must"]}, text)
    out["nothing invented"] = bool(text) and not invented(text, source + " " + c.get("file_figures", ""))
    if "trap" in chk:
        out["trap avoided"] = bool(text) and not re.search(chk["trap"], re.sub("[ً-ْ]", "", text))
    if "rows" in chk:      # each task on one line (a table row or a bullet) together with its own owner and deadline
        lines = [plain(ln) for ln in text.split("\n")]
        out["owner and deadline with each task"] = all(any(all(plain(k) in ln for k in row) for ln in lines) for row in chk["rows"])
    sentences = [s for s in re.split(r"(?<=[.!?؟])\s+|\n+", text.strip()) if len(s.split()) > 2]
    if "max_sentences" in chk:
        out["form"] = 0 < len(sentences) <= chk["max_sentences"]
    if chk.get("table"):
        out["form"] = len(re.findall(r"(?m)^\s*\|.+\|\s*$", text)) >= 3
    if "max_words" in chk:
        out["length"] = 0 < len(text.split()) <= chk["max_words"]
    want = chk.get("lang") or ("ar" if len(re.findall(r"[؀-ۿ]", c["q"])) > len(re.findall(r"[A-Za-z]", c["q"])) else "en")
    ar, la = len(re.findall(r"[؀-ۿ]", text)), len(re.findall(r"[A-Za-z]", text))
    out["language"] = bool(text) and (ar > la) == (want == "ar")
    if want == "ar" and not chk.get("bilingual_source"):       # English put in brackets after an Arabic term, when the source did not have that English
        glosses = [g for g in re.findall(r"\(([A-Za-z][A-Za-z &/-]{2,40})\)", text) if g.lower() not in source.lower()]
        out["no English glosses"] = not glosses
    if c.get("files") or c.get("paste"):
        out["sources shown"] = bool(r.get("sources"))
    if chk.get("shorter"):
        out["shorter than before"] = 0 < len(text.split()) < 0.85 * max(len(body_of(first).split()), 1)
    if chk.get("legal"):
        out["pointer to the legal demo"] = bool((r.get("summary") or {}).get("legal"))
    return out


def run(label: str) -> None:
    spec = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    rows = []
    for c in spec["cases"]:
        ids, source, q = [], "", c["q"]
        for f in c.get("files", []):
            path = D5_CONTRACT if f == "__d5_contract__" else (ROOT / f).resolve()
            up, _ = upload(path)
            ids.append(up.get("file_id"))
            if path.suffix in (".txt", ".md", ".csv"):
                source += " " + path.read_text(encoding="utf-8-sig")
        if c.get("paste"):
            pasted = (ROOT / c["paste"]).read_text(encoding="utf-8")
            q, source = f"{c['q']}\n{pasted}", pasted
        body = {"messages": [{"role": "user", "content": q}], "file_ids": [i for i in ids if i], "summary_options": c.get("options", {})}
        t, first = time.time(), ""
        if c.get("then"):
            conv = conversation()
            one = post({**body, **conv})
            first = one.get("answer", "")
            r = post({"messages": [{"role": "user", "content": c["then"]}] if conv else
                      [body["messages"][0], {"role": "assistant", "content": first}, {"role": "user", "content": c["then"]}], "file_ids": body["file_ids"], **conv})
        else:
            r = post(body)
        verdict = judge(c, r, source, first)
        row = {"id": c["id"], "q": c["q"], "summary": r.get("answer") or "", "error": r.get("error"), "s": round(time.time() - t, 1), "checks": verdict,
               "ok": all(verdict.values()), "invented": invented(body_of(r.get("answer") or ""), source + " " + c.get("file_figures", "")),
               "model": (r.get("route") or {}).get("model"), "task": (r.get("route") or {}).get("task"), "service_report": r.get("summary")}
        rows.append(row)
        bad = [k for k, v in verdict.items() if not v]
        print(f"  {'PASS' if row['ok'] else 'FAIL'} {c['id']:22} {row['s']:>5}s  {('failed: ' + ', '.join(bad)) if bad else ''}" + (f"  invented={row['invented']}" if row["invented"] else ""), flush=True)
        time.sleep(1.5)
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / f"{label}.json").write_text(json.dumps({"label": label, "cases": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    checks = [v for r in rows for v in r["checks"].values()]
    print(f"\n{label}: {sum(r['ok'] for r in rows)}/{len(rows)} summaries pass every check; {sum(checks)}/{len(checks)} individual checks pass")


def compare(a: str, *after: str) -> None:
    A = json.loads((ROOT / "results" / f"{a}.json").read_text(encoding="utf-8"))
    Bs = [json.loads((ROOT / "results" / f"{x}.json").read_text(encoding="utf-8")) for x in after]
    names: dict[str, list[int]] = {}
    for r in A["cases"]:
        for k, v in r["checks"].items():
            x = names.setdefault(k, [0, 0, 0, 0])
            x[0], x[1] = x[0] + v, x[1] + 1
    for B in Bs:
        for r in B["cases"]:
            for k, v in r["checks"].items():
                x = names.setdefault(k, [0, 0, 0, 0])
                x[2], x[3] = x[2] + v, x[3] + 1
    for k, (x, n, y, m) in names.items():
        print(f"  {k:34} {x}/{n} -> {y}/{m}")
    print(f"  {'summaries fully right':34} {sum(r['ok'] for r in A['cases'])}/{len(A['cases'])} -> {[sum(r['ok'] for r in B['cases']) for B in Bs]} of {len(A['cases'])}")
    for B in Bs:
        for r in B["cases"]:
            if not r["ok"]:
                print(f"    {B['label']} {r['id']}: {[k for k, v in r['checks'].items() if not v]}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "run":
        run(sys.argv[2])
    elif len(sys.argv) >= 4 and sys.argv[1] == "compare":
        compare(sys.argv[2], *sys.argv[3:])
    else:
        sys.exit(__doc__)
