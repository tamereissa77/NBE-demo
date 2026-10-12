"""D6 code cases (test-cases/code/cases.json): ask for each piece of code or explanation, then judge it here.

    python3 tests/d6_code_eval.py run <label>
    python3 tests/d6_code_eval.py compare <before> <after> [<after> ...]
    python3 tests/d6_code_eval.py rejudge <label>      judge a saved run again, after a change to the judge

Generated code is not judged by reading it. The test takes the code out of the answer and runs it itself, in a
separate container with no network and only the test files, then compares what it printed with the known answer:
the Python on the attached CSV or workbook, the SQL on a small copy of the loans table (translated to SQLite by
sqlglot). So a run before a change and a run after it are judged the same way, whatever the service reports.
Needs Docker and the nbe-d6 image (it has pandas and sqlglot).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from d6_files_eval import score, upload  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "test-cases" / "code"
FILES = REPO / "test-cases" / "chat-files-test"
BASE = "http://localhost:8200/api/d6"
IMAGE = "nbe-d6:nbe"
PAUSE = float(os.getenv("D6_EVAL_PAUSE", "12"))      # between cases: the hosted code model allows few tokens a minute
SQL_RUNNER = r'''
import re, sqlite3, sys, pandas as pd, sqlglot
loans = pd.read_excel("/files/branch_loans.xlsx", sheet_name="Loans", header=2)
loans.columns = ["loan_id", "branch", "customer", "product", "amount", "rate", "status", "application_date"]
loans["application_date"] = pd.to_datetime(loans["application_date"]).dt.strftime("%Y-%m-%d")
db = sqlite3.connect(":memory:")
loans.to_sql("loans", db, index=False)
db.create_function("YEAR", 1, lambda d: int(str(d)[:4]))          # MySQL and SQL Server spell it this way; SQLite has no such function
db.create_function("MONTH", 1, lambda d: int(str(d)[5:7]))
sql = open("/work/query.sql", encoding="utf-8").read()
# Any mainstream dialect is accepted: the query is read as each in turn and translated to SQLite. Dates are ISO text
# in this copy, so a DATE literal is compared as the text it holds.
last = None
for read in (None, "tsql", "mysql", "postgres", "oracle"):
    try:
        lite = sqlglot.transpile(sql, read=read, write="sqlite")[0]
        lite = re.sub(r"CAST\(('\d{4}-\d{2}-\d{2}') AS (?:DATE|TEXT)\)|DATE\(('\d{4}-\d{2}-\d{2}')\)", lambda m: m.group(1) or m.group(2), lite)
        rows = db.execute(lite).fetchall()
    except Exception as exc:
        last = exc
        continue
    for row in rows:
        print(*row)
    break
else:
    raise last
'''


def blocks(answer: str, langs: tuple[str, ...]) -> list[str]:
    return [code.strip() for lang, code in re.findall(r"```([A-Za-z+#]*)\n(.*?)```", answer, re.S) if (lang.lower() or langs[0]) in langs]


def docker(args: list[str], mounts: dict[Path, str], timeout: int = 90) -> tuple[bool, str]:
    cmd = ["docker", "run", "--rm", "--network", "none", "--memory", "2g", "--cpus", "2", "--entrypoint", "python"]
    for src, dst in mounts.items():
        cmd += ["-v", f"{src}:{dst}:ro"]
    try:
        done = subprocess.run(cmd + [IMAGE, *args], capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "timed out"
    return done.returncode == 0, (done.stdout.decode("utf-8", "replace") + ("\n" + done.stderr.decode("utf-8", "replace")[-400:] if done.returncode else "")).strip()


def run_python(code: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "code.py").write_text(code, encoding="utf-8")
        Path(tmp).chmod(0o755)
        Path(tmp, "code.py").chmod(0o644)
        # run from a folder that holds the test files under their own names, as the service's sandbox does
        return docker(["-c", "import os, shutil, runpy; os.makedirs('/tmp/w'); [shutil.copy('/files/' + f, '/tmp/w') for f in os.listdir('/files') if os.path.isfile('/files/' + f)]; "
                             "os.chdir('/tmp/w'); runpy.run_path('/work/code.py', run_name='__main__')"], {FILES: "/files", Path(tmp): "/work"})


def run_sql(sql: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "query.sql").write_text(sql.rstrip().rstrip(";"), encoding="utf-8")
        Path(tmp).chmod(0o755)
        Path(tmp, "query.sql").chmod(0o644)
        return docker(["-c", SQL_RUNNER], {FILES: "/files", Path(tmp): "/work"})


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


def judge(c: dict, r: dict) -> tuple[dict, str]:
    chk, text = c["check"], r.get("answer") or ""
    out: dict[str, bool] = {"recognised as code": (r.get("route") or {}).get("task") == "code"}
    printed = ""
    if "run" in chk:
        code = blocks(text, ("python", "py"))
        ok, printed = run_python(code[-1]) if code else (False, "no Python in the answer")      # the last block is the complete, final one
        out["the code runs"] = ok
        out["and gives the right result"] = ok and score({"expect": chk["run"]}, printed)
    if "sql" in chk:
        code = blocks(text, ("sql",))
        ok, printed = run_sql(code[-1]) if code else (False, "no SQL in the answer")
        out["the code runs"] = ok
        out["and gives the right result"] = ok and score({"expect": chk["sql"]}, printed)
    prose = re.sub(r"```.*?```", " ", text, flags=re.S)
    if "must" in chk:
        out["says what it must"] = bool(text) and score({"expect": chk["must"]}, text)
    if "must_not" in chk:
        out["right dialect"] = bool(text) and not any(re.search(chk["must_not"], b, re.I) for b in re.findall(r"```[A-Za-z]*\n(.*?)```", text, re.S) or [text])
    if "max_words" in chk:
        out["brief"] = 0 < len(prose.split()) <= chk["max_words"]
    if "reply_lang" in chk:
        ar, la = len(re.findall(r"[؀-ۿ]", prose)), len(re.findall(r"[A-Za-z]", prose))
        out["explained in the language asked"] = (ar > 0.6 * la) == (chk["reply_lang"] == "ar")
    report = r.get("code") or {}
    if "warns" in chk:
        out["warning raised by the service"] = any(chk["warns"] in json.dumps(w).lower() for w in report.get("warnings", []))
    if "masked" in chk:
        out["secrets kept from the model"] = report.get("masked", 0) >= chk["masked"]
    if c.get("files") and "run" in chk:
        ran = [b.get("run") for b in report.get("blocks", []) if b.get("run")]
        out["run for the user, output shown"] = bool(ran) and ran[-1].get("ok") is True
    return out, printed


def run(label: str) -> None:
    spec = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    rows = []
    for c in spec["cases"]:
        ids = [upload((ROOT / f).resolve())[0].get("file_id") for f in c.get("files", [])]
        t = time.time()
        r = post({"messages": [{"role": "user", "content": c["q"]}], "file_ids": [i for i in ids if i], "code_options": c.get("options", {})})
        verdict, printed = judge(c, r)
        row = {"id": c["id"], "q": c["q"][:160], "answer": r.get("answer") or "", "error": r.get("error"), "s": round(time.time() - t, 1), "checks": verdict,
               "ok": all(verdict.values()), "printed": printed[:600], "model": (r.get("route") or {}).get("model"), "task": (r.get("route") or {}).get("task"), "service_report": r.get("code")}
        rows.append(row)
        bad = [k for k, v in verdict.items() if not v]
        print(f"  {'PASS' if row['ok'] else 'FAIL'} {c['id']:20} {row['s']:>5}s {str(row['model'])[:22]:22} {('failed: ' + ', '.join(bad)) if bad else ''}"
              + (f"  | {printed[-90:]!r}" if bad and printed else ""), flush=True)
        time.sleep(PAUSE)
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / f"{label}.json").write_text(json.dumps({"label": label, "cases": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    checks = [v for r in rows for v in r["checks"].values()]
    print(f"\n{label}: {sum(r['ok'] for r in rows)}/{len(rows)} cases pass every check; {sum(checks)}/{len(checks)} individual checks pass")


def rejudge(label: str) -> None:
    """Judge the saved answers of a run again (after a change to the judge itself), without asking the service again."""
    path = ROOT / "results" / f"{label}.json"
    saved, cases = json.loads(path.read_text(encoding="utf-8")), {c["id"]: c for c in json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))["cases"]}
    for row in saved["cases"]:
        row["checks"], printed = judge(cases[row["id"]], {"answer": row["answer"], "route": {"task": row["task"]}, "code": row.get("service_report")})
        row["ok"], row["printed"] = all(row["checks"].values()), printed[:600]
        print(f"  {'PASS' if row['ok'] else 'FAIL'} {row['id']:20} {[k for k, v in row['checks'].items() if not v] or ''}")
    path.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{label}: {sum(r['ok'] for r in saved['cases'])}/{len(saved['cases'])} cases pass every check")


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
        print(f"  {k:34} {x}/{n} -> {y}/{m}")
    print(f"  {'cases fully right':34} {sum(r['ok'] for r in A['cases'])}/{len(A['cases'])} -> {[sum(r['ok'] for r in B['cases']) for B in Bs]} of {len(A['cases'])}")
    for B in Bs:
        for r in B["cases"]:
            if not r["ok"]:
                print(f"    {B['label']} {r['id']}: {[k for k, v in r['checks'].items() if not v]}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "run":
        run(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == "rejudge":
        rejudge(sys.argv[2])
    elif len(sys.argv) >= 4 and sys.argv[1] == "compare":
        compare(sys.argv[2], *sys.argv[3:])
    else:
        sys.exit(__doc__)
