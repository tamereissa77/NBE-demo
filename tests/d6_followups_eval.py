"""D6 follow-up questions (test-cases/chat-followups/scenarios.json): play each multi-turn scenario against the
running service the way the portal would, score the checked turns, save the run under a label.

    python3 tests/d6_followups_eval.py run <label> --old-portal   emulate the portal before conversations existed:
                                                                  the browser keeps the history and sends the last 6 messages
    python3 tests/d6_followups_eval.py run <label>                use the conversation API (the server keeps the history)
    python3 tests/d6_followups_eval.py compare <before> <after>

A scenario with `reload_before_turn` simulates a page reload: everything the browser held is dropped and only what
the server can give back is used from that turn on. Standard library only; runs on the host against the gateway.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from d6_files_eval import norm, score, upload  # noqa: E402 - same scoring rules as the file-chat set

ROOT = Path(__file__).resolve().parents[1] / "test-cases" / "chat-followups"
BASE = "http://localhost:8200/api/d6"
PAUSE = 1.5


def http(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(BASE + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json"}, method=method)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == 3:
                return e.code, {"error": e.read().decode(errors="replace")[:200]}
            time.sleep(20)                                # a rate-limited model surfaces as a 5xx
        except Exception as e:  # noqa: BLE001
            return 0, {"error": f"{type(e).__name__}: {e}"}
    return 0, {}


def reply_lang(answer: str) -> str:
    """Language of the answer itself, ignoring code blocks and inline code."""
    text = re.sub(r"```.*?```|`[^`]*`", " ", answer, flags=re.S)
    ar, la = len(re.findall(r"[؀-ۿ]", text)), len(re.findall(r"[A-Za-z]", text))
    return "ar" if ar >= 0.4 * max(ar + la, 1) else "en"


def judge(check: dict, r: dict, restored: int | None) -> dict:
    """Each key of the check -> passed?"""
    route, answer = r.get("route") or {}, r.get("answer") or ""
    out = {}
    for key in ("task", "alias", "lang"):
        if key in check:
            out[key] = route.get(key) == check[key]
    if "reply_lang" in check:
        out["reply_lang"] = bool(answer) and reply_lang(answer) == check["reply_lang"]
    if "contains" in check:
        out["contains"] = bool(answer) and score({"expect": check["contains"]}, answer)
    if "retrieval_has" in check:
        found = [str(n) for s in r.get("trace") or [] if s.get("kind") == "retrieval" for n in (s.get("detail") or [])]
        out["retrieval_has"] = any(check["retrieval_has"].lower() in n.lower() for n in found)
    if "restored" in check:
        out["restored"] = restored is not None and restored >= check["restored"]
    return out


def play(s: dict, old_portal: bool) -> list[dict]:
    file_id = None
    if s.get("file"):
        up, _ = upload((ROOT / s["file"]).resolve())
        file_id = up.get("file_id")
    browser: list[dict] = []                # what the browser tab holds: the visible conversation
    conv = None if old_portal else http("POST", "/conversation", {})[1].get("conversation_id")
    rows = []
    for i, turn in enumerate(s["turns"], start=1):
        restored = None
        if s.get("reload_before_turn") == i:
            browser = []                    # the tab is reloaded: its memory is gone
            status, back = http("GET", f"/conversation/{conv}") if conv else (404, {})
            if status == 200:
                browser = [{"role": m["role"], "content": m["content"]} for m in back.get("messages", [])]
            restored = len(browser) // 2
        browser.append({"role": "user", "content": turn["q"]})
        if old_portal:
            body = {"messages": browser[-6:], "file_id": file_id}
        else:
            body = {"conversation_id": conv, "messages": browser[-1:], "file_id": file_id}
        t = time.time()
        status, r = http("POST", "/chat", body)
        secs = round(time.time() - t, 1)
        answer = r.get("answer", "")
        browser.append({"role": "assistant", "content": answer})
        route = r.get("route") or {}
        row = {"turn": i, "q": turn["q"], "answer": answer, "error": r.get("error"), "s": secs,
               "task": route.get("task"), "alias": route.get("alias"), "lang": route.get("lang"), "how": route.get("how"),
               "model": route.get("model"), "restored": restored}
        if "check" in turn:
            row["checks"] = judge(turn["check"], r, restored)
            row["ok"] = all(row["checks"].values())
        rows.append(row)
        mark = "    " if "check" not in turn else ("PASS" if row["ok"] else "FAIL")
        failed = "" if row.get("ok", True) else " [" + ", ".join(k for k, v in row["checks"].items() if not v) + "]"
        print(f"  {mark} t{i} {secs:>5}s {str(row['task']):11} {str(row['lang']):2} | {turn['q'][:38]!r:42} -> {(row['error'] or answer)[:60]!r}{failed}", flush=True)
        time.sleep(PAUSE)
    return rows


def run(label: str, old_portal: bool) -> None:
    spec = json.loads((ROOT / "scenarios.json").read_text(encoding="utf-8"))
    out = {"label": label, "mode": "old portal (last 6 messages)" if old_portal else "conversation API", "scenarios": []}
    only = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--only=")]          # --only=hand-off runs one hypothesis
    for s in spec["scenarios"]:
        if only and s["hypothesis"] not in only and s["id"] not in only:
            continue
        print(f"\n== {s['id']} ({s['hypothesis']})", flush=True)
        out["scenarios"].append({"id": s["id"], "hypothesis": s["hypothesis"], "turns": play(s, old_portal)})
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / f"{label}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    scored = [t["ok"] for s in out["scenarios"] for t in s["turns"] if "ok" in t]
    print(f"\n{label}: {sum(scored)}/{len(scored)} checked turns passed; saved results/{label}.json")


def compare(a: str, b: str) -> None:
    A, B = (json.loads((ROOT / "results" / f"{x}.json").read_text(encoding="utf-8")) for x in (a, b))
    sb = {s["id"]: s for s in B["scenarios"]}
    groups: dict[str, list[int]] = {}
    for s in A["scenarios"]:
        g = sb.get(s["id"])
        if not g:
            continue
        ta, tb = [t for t in s["turns"] if "ok" in t], [t for t in g["turns"] if "ok" in t]
        x = groups.setdefault(s["hypothesis"], [0, 0, 0])
        x[0], x[1], x[2] = x[0] + sum(t["ok"] for t in ta), x[1] + sum(t["ok"] for t in tb), x[2] + len(ta)
        print(f"{s['id']:26} {sum(t['ok'] for t in ta)}/{len(ta)} -> {sum(t['ok'] for t in tb)}/{len(tb)}")
        for p, q in zip(ta, tb):
            if p["ok"] != q["ok"]:
                print(f"    t{p['turn']} {'PASS' if p['ok'] else 'FAIL'} -> {'PASS' if q['ok'] else 'FAIL'}  {p['q'][:50]!r}")
    print()
    for name, (x, y, n) in groups.items():
        print(f"  {name:12} {x}/{n} -> {y}/{n}")
    print(f"  {'TOTAL':12} {sum(v[0] for v in groups.values())}/{sum(v[2] for v in groups.values())} -> "
          f"{sum(v[1] for v in groups.values())}/{sum(v[2] for v in groups.values())}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "run":
        run(sys.argv[2], "--old-portal" in sys.argv)
    elif len(sys.argv) == 4 and sys.argv[1] == "compare":
        compare(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
