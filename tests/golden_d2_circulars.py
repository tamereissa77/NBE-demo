"""D2 golden set for the scanned corpus (data/seed/golden/d2_circulars.json): run every question through /ask
with its role and check the outcome.
answer: found, the expected document is cited with crop images, and an expected phrase is in the answer.
restricted: the role may not read the document that answers it; the reply says so and returns no sources.
open: a procedure question from a limited role; it must be answered, never reported as restricted.
unanswerable: not found, and not reported as restricted.
Also prints the reranker score of the top source per case type, for calibrating the cut-offs in app/main.py."""
import json
import sys
import urllib.request

B = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8200/api/d2"
golden = json.load(open("/data/seed/golden/d2_circulars.json", encoding="utf-8"))
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
ok: dict[str, list[int]] = {}
top: dict[str, list[float]] = {}
misses = []
for g in golden:
    body = json.dumps({"question": g["question"], "role": g["role"]}).encode()
    r = json.load(urllib.request.urlopen(urllib.request.Request(f"{B}/ask", body, {"Content-Type": "application/json"}), timeout=600))
    cited = [c for c in r["citations"] if c["cited"]]
    restricted = bool(r.get("restricted"))
    if g["type"] == "answer":
        ans = r["answer"].translate(DIGITS).lower()
        good = (r["found"] and any(c.get("doc_id") == g["doc"] and c.get("crops") for c in cited)
                and any(e.translate(DIGITS).lower() in ans for e in g["expect_any"]))
    elif g["type"] == "restricted":
        good = restricted and not r["citations"]
    elif g["type"] == "open":
        good = r["found"] and not restricted
    else:
        good = not r["found"] and not restricted
    ok.setdefault(g["type"], [0, 0])
    ok[g["type"]][0] += good
    ok[g["type"]][1] += 1
    if r["citations"]:
        top.setdefault(g["type"], []).append(max(c["rerank"] for c in r["citations"]))
    if not good:
        misses.append({"type": g["type"], "role": g["role"], "q": g["question"], "found": r["found"], "restricted": restricted,
                       "answer": r["answer"][:200], "cited": sorted({c.get("doc_id") or c["file"] for c in cited})})
print(json.dumps({k: f"{a}/{n}" for k, (a, n) in ok.items()}))
print(json.dumps({k: {"min": min(v), "max": max(v)} for k, v in top.items()}))
print(json.dumps(misses[:8], ensure_ascii=False, indent=1))
