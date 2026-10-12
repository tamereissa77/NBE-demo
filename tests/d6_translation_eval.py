"""D6 translation cases (test-cases/translation/cases.json), Arabic and English in both directions: ask for each
translation, then judge it with checks computed here, so a run before a change and a run after are judged alike.

    python3 tests/d6_translation_eval.py run <label>
    python3 tests/d6_translation_eval.py compare <before> <after> [<after> ...]

Whole-file cases use documents of one to three pages; longer ones are left out on purpose (the hosted model's
token allowance). Standard library only; runs on the host against the gateway.
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

ROOT = Path(__file__).resolve().parents[1] / "test-cases" / "translation"
BASE = "http://localhost:8200/api/d6"
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def plain(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(DIGITS)
    text = re.sub("[ً-ْـ]", "", text).replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
    text = re.sub("[‐-―]", "-", text).replace(" ", " ").replace(" ", " ")
    return re.sub(r"(?<=\d)[,٬](?=\d{3})", "", text).lower()


def figures(text: str) -> list[str]:
    """Numbers of two or more digits and reference codes: what must come through a translation unchanged."""
    t = plain(text)
    codes = re.findall(r"[a-z]{1,10}(?:[-/][a-z0-9]+)*[-/]\d[a-z0-9/-]*", t)
    for c in codes:
        t = t.replace(c, " ")
    return list(dict.fromkeys(codes + [n for n in re.findall(r"\d+(?:\.\d+)?", t) if len(n.lstrip("0")) >= 2]))


def post(body: dict) -> dict:
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE + "/chat", json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=900) as r:
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


def judge(c: dict, r: dict) -> dict:
    chk, text = c["check"], r.get("answer") or ""
    out: dict[str, bool] = {}
    if chk.get("asks"):
        out["asks for the text"] = bool(text) and len(text.split()) < 60 and bool(re.search(r"[?؟]|يرجى|برجاء|الرجاء|الصق|أرفق|paste|attach|provide", text))
        return out
    out["recognised as a translation"] = (r.get("route") or {}).get("task") == "translation"
    ar, la = len(re.findall(r"[؀-ۿ]", text)), len(re.findall(r"[A-Za-z]", text))
    out["right language"] = bool(text) and (ar > la) == (chk["to"] == "ar")
    t = plain(text)
    want = (chk.get("figures", "").split() if "figures" in chk else []) + (figures((ROOT / chk["source"]).read_text(encoding="utf-8")) if chk.get("source") else [])
    if want:
        missing = [f for f in dict.fromkeys(want) if not re.search(rf"(?<![\d.]){re.escape(f)}(?!\d)", t)]
        out["every figure kept"] = bool(text) and not missing
        out["_missing"] = missing                                  # shown in the run log, not counted
    for k in chk.get("keep", []):
        out["every figure kept"] = out.get("every figure kept", True) and k.lower() in text.lower()
    if "complete" in chk:
        out["complete to the end"] = bool(text) and score({"expect": chk["complete"]}, text[-900:])
    if "terms" in chk:
        out["the bank's terms used"] = bool(text) and score({"expect": chk["terms"]}, text)
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if "min_lines" in chk:
        out["layout kept"] = len(lines) >= chk["min_lines"]
    if "headings" in chk:
        out["layout kept"] = len([ln for ln in lines if ln.lstrip().startswith("#")]) >= chk["headings"]
    if "table_rows" in chk:
        out["layout kept"] = len([ln for ln in lines if ln.strip().startswith("|")]) >= chk["table_rows"]
    if chk.get("clean"):
        out["no stray marks"] = bool(text) and not re.search(r"\[S\d+\]|\[Page \d+\]|\[صفحة \d+\]|<<\d+>>", text)
    if chk.get("arabic_digits"):
        out["numerals as chosen"] = bool(re.search("[٠-٩]", text)) and not re.search(r"\d", text.translate(str.maketrans("", "", "٠١٢٣٤٥٦٧٨٩")))
    if "of" in chk:        # what was translated: the answer just given (about as long as it), or the file (much longer)
        first = len((r.get("_first") or "").split())
        out["translated the right thing"] = bool(text) and first > 0 and ((len(text.split()) < 2.2 * first) if chk["of"] == "answer" else (len(text.split()) > 1.5 * first))
    if chk.get("aligned"):
        rep = r.get("translation") or {}
        out["aligned paragraph by paragraph"] = bool(rep.get("segments")) and rep.get("translated") == rep.get("total")
    return out


def run(label: str) -> None:
    spec = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    rows = []
    for c in spec["cases"]:
        ids = [upload((ROOT / f).resolve())[0].get("file_id") for f in c.get("files", [])]
        body = {"messages": [{"role": "user", "content": c["q"]}], "file_ids": [i for i in ids if i], "translation_options": c.get("options", {})}
        t = time.time()
        if c.get("then"):
            conv = conversation()
            one = post({**body, **conv})
            r = post({"messages": [{"role": "user", "content": c["then"]}] if conv else
                      [body["messages"][0], {"role": "assistant", "content": one.get("answer", "")}, {"role": "user", "content": c["then"]}], "file_ids": body["file_ids"], **conv})
            r["_first"] = one.get("answer", "")
        else:
            r = post(body)
        verdict = judge(c, r)
        missing = verdict.pop("_missing", [])
        rep = r.get("translation") or {}
        row = {"id": c["id"], "q": c["q"][:200], "translation": r.get("answer") or "", "error": r.get("error"), "s": round(time.time() - t, 1), "checks": verdict,
               "ok": all(verdict.values()), "missing_figures": missing, "model": (r.get("route") or {}).get("model"),
               "service_report": {k: rep.get(k) for k in ("direction", "total", "translated", "to_check", "complete")} if rep else None}
        rows.append(row)
        bad = [k for k, v in verdict.items() if not v]
        print(f"  {'PASS' if row['ok'] else 'FAIL'} {c['id']:22} {row['s']:>5}s {len(row['translation']):>6} chars  {('failed: ' + ', '.join(bad)) if bad else ''}"
              + (f"  missing={missing[:6]}" if missing else ""), flush=True)
        time.sleep(1.5)
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / f"{label}.json").write_text(json.dumps({"label": label, "cases": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    checks = [v for r in rows for v in r["checks"].values()]
    print(f"\n{label}: {sum(r['ok'] for r in rows)}/{len(rows)} translations pass every check; {sum(checks)}/{len(checks)} individual checks pass")


def compare(a: str, *after: str) -> None:
    A = json.loads((ROOT / "results" / f"{a}.json").read_text(encoding="utf-8"))
    Bs = [json.loads((ROOT / "results" / f"{x}.json").read_text(encoding="utf-8")) for x in after]
    names: dict[str, list[int]] = {}
    for i, runs in enumerate(([A], Bs)):
        for B in runs:
            for r in B["cases"]:
                for k, v in r["checks"].items():
                    x = names.setdefault(k, [0, 0, 0, 0])
                    x[2 * i], x[2 * i + 1] = x[2 * i] + v, x[2 * i + 1] + 1
    for k, (x, n, y, m) in names.items():
        print(f"  {k:32} {x}/{n} -> {y}/{m}")
    print(f"  {'translations fully right':32} {sum(r['ok'] for r in A['cases'])}/{len(A['cases'])} -> {[sum(r['ok'] for r in B['cases']) for B in Bs]} of {len(A['cases'])}")
    for B in Bs:
        for r in B["cases"]:
            if not r["ok"]:
                print(f"    {B['label']} {r['id']}: {[k for k, v in r['checks'].items() if not v]} {r['missing_figures'][:5] or ''}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "run":
        run(sys.argv[2])
    elif len(sys.argv) >= 4 and sys.argv[1] == "compare":
        compare(sys.argv[2], *sys.argv[3:])
    else:
        sys.exit(__doc__)
