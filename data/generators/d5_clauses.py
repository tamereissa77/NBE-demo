"""D5 contract clauses, written out deterministically rather than by the LLM.

The template comparison is only meaningful if each planted deviation is really in the text, so every
term in specs.TEMPLATE_CLAUSES / specs.CONTRACTS appears here verbatim (checked by build()).
Synthetic demo contracts, not any bank's real terms. The article text lives in specs.py (per bank branch).
"""
import json
from pathlib import Path

from data.generators import specs

OUT = Path("/repo/data/seed/d5")

TEMPLATE, DEVIATIONS = specs.CLAUSE_TEXT, specs.DEVIATION_TEXT

def article(title: str, body: str) -> str:
    return f"## {title}\n\n{body}"


def check() -> list[str]:
    problems = []
    for c in specs.TEMPLATE_CLAUSES:
        text = TEMPLATE[c["key"]][1]
        problems += [f"template {c['key']}: {v}" for v in c["facts"].values() if v not in text]
    for k in specs.CONTRACTS:
        for d in k["deviations"]:
            text = DEVIATIONS[(k["id"], d["clause"])][1]
            problems += [f"{k['id']} {d['clause']}: {v}" for v in d["facts"].values() if v not in text]
    return problems


def build() -> dict:
    problems = check()
    assert not problems, problems
    OUT.mkdir(parents=True, exist_ok=True)
    order = [c["key"] for c in specs.TEMPLATE_CLAUSES]
    by_key = {c["key"]: c for c in specs.TEMPLATE_CLAUSES}
    (OUT / "template.md").write_text("# نموذج عقد تمويل شخصي معتمد\n\nنموذج تجريبي لأغراض العرض. ليس عقداً حقيقياً.\n\n" +
                                     "\n\n".join(article(*TEMPLATE[k]) for k in order) + "\n", encoding="utf-8")
    contracts = []
    for k in specs.CONTRACTS:
        parts = []
        for key in order:
            if key in k.get("missing", []):
                continue
            title, body = DEVIATIONS.get((k["id"], key), TEMPLATE[key])
            body = body.replace(specs.PH_BORROWER, k["borrower"]).replace("[المبلغ]", k["amount"]).replace("[عدد الأقساط]", k["installments"])
            parts.append(article(title, body))
        (OUT / f"{k['id']}.md").write_text(
            f"# عقد تمويل رقم {k['id']}\n\n{specs.BORROWER_LABEL}: {k['borrower']} · قيمة التمويل: {k['amount']} · عدد الأقساط: {k['installments']}\n\n"
            "عقد تجريبي لأغراض العرض.\n\n" + "\n\n".join(parts) + "\n", encoding="utf-8")
        contracts.append({"file": f"{k['id']}.md", "borrower": k["borrower"], "deviations":
            [{"clause": d["clause"], "title": by_key[d["clause"]]["title"], "severity": d["severity"], "why_ar": d["why_ar"],
              "template_facts": by_key[d["clause"]]["facts"], "contract_facts": d["facts"]} for d in k["deviations"]] +
            [{"clause": m, "title": by_key[m]["title"], "severity": "high", "why_ar": "المادة محذوفة بالكامل من العقد",
              "template_facts": by_key[m]["facts"], "contract_facts": None} for m in k.get("missing", [])]})
    # E01 is a hand translation of C01 into English (English-path test); it carries C01's planted deviation
    if (OUT / "E01.md").exists():
        c01 = next(c for c in contracts if c["file"] == "C01.md")
        contracts.append({**c01, "file": "E01.md", "lang": "en", "borrower": "Al-Ofok Trading Company (specimen)"})
    rulings = [{"file": f"{r['id']}.md", **r} for r in specs.RULINGS if (OUT / f"{r['id']}.md").exists()]
    manifest = {"template": "template.md", "contracts": contracts, "rulings": rulings,
                "note": "Clauses written deterministically (d5_clauses.py); rulings authored by the on-box LLM."}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    golden = Path("/repo/data/seed/golden")
    golden.mkdir(parents=True, exist_ok=True)
    (golden / "d5.json").write_text(json.dumps(contracts, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"contracts": len(contracts), "rulings": len(rulings)}


if __name__ == "__main__":
    print("D5:", build())
