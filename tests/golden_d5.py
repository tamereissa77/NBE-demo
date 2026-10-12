"""D5 golden check against a running service. Every planted deviation in manifest.json (including the
English contract E01) is caught at its manifest severity with no false deviations; contract key points
carry their article tag; rulings surface the awarded amounts (R01 47,300; R02 72,000 and 48,000 lead,
not the 120,000 in dispute) with court/outcome/award_split filled. Uses /analyze/refresh so cached
results are not reused.

    python tests/golden_d5.py [base_url] [seed_dir] [--json out.json]
"""
import json
import re
import sys
import urllib.request

args = [a for a in sys.argv[1:] if not a.startswith("--")]
B = args[0] if args else "http://localhost:8200/api/d5"
SEED = args[1] if len(args) > 1 else "/data/seed/d5"
OUT = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None
manifest = json.load(open(f"{SEED}/manifest.json", encoding="utf-8"))
template_titles = {m.group(2).strip(): int(m.group(1)) for m in
                   re.finditer(r"المادة\s+(\d+)\s*-\s*([^\n]+)", open(f"{SEED}/template.md", encoding="utf-8").read())}
TAG = re.compile(r"^\s*\[\s*(?:م\.?|Art\.?)\s*\d+\s*\]")


def analyze(name: str) -> dict:
    req = urllib.request.Request(f"{B}/analyze/refresh", json.dumps({"file": name}).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=900))


def digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def latin_share(s: str) -> float:
    a, l = len(re.findall(r"[؀-ۿ]", s)), len(re.findall(r"[A-Za-z]", s))
    return l / max(a + l, 1)


failures, report = [], {}
caught = planted = sev_ok = 0
for c in manifest["contracts"]:
    r = analyze(c["file"])
    f = c["file"]
    want = {template_titles[d["title"]]: d["severity"] for d in c["deviations"]}
    rows = {row["article"]: row for row in r["diff"]}
    got = {a for a, row in rows.items() if row["status"] in ("deviates", "missing")}
    unchecked = sorted(a for a, row in rows.items() if row["status"] == "unchecked")
    if unchecked:
        failures.append(f"{f}: articles {unchecked} could not be compared (malformed model output)")
    planted += len(want)
    caught += len(set(want) & got)
    sev = {a: rows[a]["severity"] for a in want if a in rows}
    sev_ok += sum(sev.get(a) == s for a, s in want.items())
    if set(want) - got:
        failures.append(f"{f}: missed articles {sorted(set(want) - got)}")
    if got - set(want):
        failures.append(f"{f}: false deviations on articles {sorted(got - set(want))}")
    for a, s in want.items():
        if a in got and sev.get(a) != s:
            failures.append(f"{f}: article {a} severity {sev.get(a)}, manifest says {s}")
    untagged = [k for k in r["summary"]["key_points"] if not TAG.match(k)]
    if untagged:
        failures.append(f"{f}: {len(untagged)} key point(s) without an article tag")
    if r["summary"].get("court") is not None or r["summary"].get("award_split") is not None:
        failures.append(f"{f}: ruling fields set on a contract")
    if not r.get("analyzed_at"):
        failures.append(f"{f}: no analyzed_at")
    if c.get("lang") == "en" and latin_share(" ".join(r["summary"]["key_points"])) < 0.8:
        failures.append(f"{f}: English contract summarised in Arabic")
    compound = [x for x in r["risk_flags"] if x.get("compound")]
    # Compound risks are derived from the deviating articles (THEMES in main.py). No seed contract has
    # two deviating articles in one theme, so none may fire.
    if compound:
        failures.append(f"{f}: unexpected compound risk on {[x['articles'] for x in compound]}")
    report[f] = {"flagged": sorted(got), "severity": sev, "compound": [x["articles"] for x in compound],
                 "article_refs": r["summary"].get("article_refs")}
    print(f, "planted", want, "flagged", sorted(got), "severity", sev, "compound", report[f]["compound"])

BEARER = {"R02.md": {"72000": "بنك", "48000": "أحمد"}}
expect = {"R01.md": (["47300"], "47300", False), "R02.md": (["72000", "48000"], "72000", True), "R03.md": ([], None, False)}
for name, (must, headline, split) in expect.items():
    r = analyze(name)
    s = r["summary"]
    amounts = s["amounts"]
    found = {digits(n) for a in amounts for n in re.findall(r"\d[\d,]*", a)}
    split_amounts = {digits(x["amount"]) for x in s.get("award_split") or []}
    report[name] = {"amounts": amounts, "court": s.get("court"), "outcome": s.get("outcome"), "award_split": s.get("award_split"),
                    "self_check_flags": len(r["risk_flags"])}
    print(name, amounts, "| court:", s.get("court"), "| split:", s.get("award_split"), "| self-check flags:", len(r["risk_flags"]))
    for m in must:
        if m not in found:
            failures.append(f"{name}: amount {m} missing from summary amounts")
    if headline and (not amounts or headline not in digits(amounts[0])):
        failures.append(f"{name}: headline amount is {amounts[:1]}, expected {headline}")
    if headline and amounts and "جنيه مصري" not in amounts[0]:
        failures.append(f"{name}: headline amount {amounts[0]!r} lost its currency unit")
    if not s.get("court") or not s.get("outcome"):
        failures.append(f"{name}: court/outcome not filled")
    real_court = next(x["court"] for x in manifest["rulings"] if x["file"] == name).split("(")[0].strip()
    if s.get("court") and real_court not in s["court"] and s["court"].split("(")[0].strip() not in real_court:
        failures.append(f"{name}: court {s['court']!r}, document says {real_court!r}")
    if split and not set(must) <= split_amounts:
        failures.append(f"{name}: award_split {s.get('award_split')} lacks {must}")
    # Who bears which amount: R02's bank pays 72,000 to the plaintiff, who bears 48,000 himself
    for amount, who in BEARER.get(name, {}).items():
        rows = [x for x in s.get("award_split") or [] if digits(x["amount"]) == amount]
        if not rows or who not in rows[0]["party"]:
            failures.append(f"{name}: {amount} should be borne by {who!r}, split says {[x['party'] for x in rows]}")

summary = {"planted_caught": f"{caught}/{planted}", "severity_match": f"{sev_ok}/{planted}", "failures": failures}
print(json.dumps(summary, ensure_ascii=False, indent=1))
if OUT:
    json.dump({**summary, "docs": report}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
sys.exit(1 if failures else 0)
