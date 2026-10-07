"""D2 golden set (data/seed/golden/d2.json, derived from the fact sheets): run every question through
/ask and check the answer. current_value: expected numbers appear and the right procedure is cited.
delta: the right procedure is cited and a version comparison is returned. unanswerable: not found."""
import json
import re
import sys
import urllib.request

B = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8200/api/d2"
golden = json.load(open("/data/seed/golden/d2.json", encoding="utf-8"))
ok = {"current_value": [0, 0], "delta": [0, 0], "unanswerable": [0, 0]}
misses = []
for g in golden:
    r = json.load(urllib.request.urlopen(urllib.request.Request(f"{B}/ask", json.dumps({"question": g["question"]}).encode(),
                                                                {"Content-Type": "application/json"}), timeout=300))
    cited = {c["file"].split("_")[0] for c in r["citations"] if c["cited"]}
    if g["type"] == "unanswerable":
        good = not r["found"]
    elif g["type"] == "delta":
        good = g["procedure"] in cited and r["delta"] is not None
    else:
        nums = re.findall(r"\d[\d,.]*", g["expected"])
        ans = r["answer"].replace("٫", ".")
        good = g["procedure"] in cited and all(n.rstrip(".,") in ans for n in nums)
    ok[g["type"]][0] += good
    ok[g["type"]][1] += 1
    if not good:
        misses.append({"q": g["question"], "expected": g.get("expected"), "answer": r["answer"][:200], "cited": sorted(cited)})
print(json.dumps({k: f"{a}/{n}" for k, (a, n) in ok.items()}))
print(json.dumps(misses[:8], ensure_ascii=False, indent=1))
