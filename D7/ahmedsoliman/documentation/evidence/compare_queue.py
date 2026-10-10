"""Throw-away: the same counts on a queue snapshot before and after the policy changes."""
import json, re, sys

OFFICIAL = json.load(open("/home/asoliman/projects/NBE-demo/data/seed/d7/policy.json"))["teams_en"]


def stats(path):
    q = json.load(open(path))
    s = {"n": len(q), "topic_exact": 0, "sev_exact": 0, "policy_ok": 0, "guard_ok": 0, "two_attempts": 0,
         "final_reply": [], "en": 0, "en_official_team": 0, "en_other_team": [], "social": 0, "social_named": 0,
         "social_len": [], "social_figures": 0, "social_private": 0, "social_has_id": 0, "nonsocial_len": []}
    for r in q:
        t = r["triage"]; d = t["draft"]
        s["topic_exact"] += t["topic"] == t["labels"]["topic"]; s["sev_exact"] += t["severity"] == t["labels"]["severity"]
        s["policy_ok"] += t["policy_ok"]; s["guard_ok"] += t["guardrail"]["allowed"]
        s["two_attempts"] += sum(1 for x in t["trace"] if x["label"].startswith("Draft")) > 1
        if re.search(r"الرد النهائي|رد نهائي|final (reply|response|answer|decision|resolution)", d, re.I):
            s["final_reply"].append(r["id"])
        if t["language"] == "en":
            s["en"] += 1
            if OFFICIAL[t["topic"]] in d:
                s["en_official_team"] += 1
            elif re.search(r"\b(department|division|unit)\b", d, re.I):
                s["en_other_team"].append(r["id"])
        if r["channel"] == "social":
            s["social"] += 1; s["social_len"].append(len(d))
            parts = [p for p in r["customer_name"].split() if len(p) >= 3]
            s["social_named"] += bool(re.search(r"عزيز[يت]|عزيزنا|الأستاذ|السيدة?\b|\bDear\b", d) or any(p in d for p in parts))
            s["social_figures"] += bool(re.search(r"[0-9٠-٩]", d.replace(r["id"], "")))
            s["social_private"] += bool(re.search(r"رسال\S*\s+خاص|الرسائل الخاصة|على الخاص|private message|direct message|\bDM\b", d, re.I))
            s["social_has_id"] += r["id"] in d
        else:
            s["nonsocial_len"].append(len(d))
    for k in ("social_len", "nonsocial_len"):
        v = s[k]; s[k] = f"min {min(v)} mean {sum(v) // len(v)} max {max(v)}"
    return s, q


for p in sys.argv[1:]:
    s, q = stats(p)
    print("==", p)
    for k, v in s.items():
        print(f"  {k}: {v}")
    if "--drafts" in p or p.endswith("after.json"):
        for r in q:
            t = r["triage"]
            if r["channel"] == "social" or t["language"] == "en" or not t["policy_ok"]:
                print("--", r["id"], r["channel"], t["language"], "policy_ok", t["policy_ok"], t["policy_violations"]); print(t["draft"])
