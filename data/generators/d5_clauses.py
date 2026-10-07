"""D5 contract clauses, written out deterministically rather than by the LLM.

The template comparison is only meaningful if each planted deviation is really in the text, so every
term in specs.TEMPLATE_CLAUSES / specs.CONTRACTS appears here verbatim (checked by build()).
Synthetic demo contracts, not NBE's real terms.
"""
import json
from pathlib import Path

from data.generators import specs

OUT = Path("/repo/data/seed/d5")

TEMPLATE = {
    "parties": ("المادة 1 - الأطراف",
                f"أُبرم هذا العقد بين {specs.BANK_AR} (نموذج تجريبي) ويُشار إليه فيما يلي بـ\"المقرض\"، وبين [اسم المقترض] ويُشار إليه فيما يلي "
                "بـ\"المقترض\". ويقر الطرفان بأهليتهما الكاملة للتعاقد، وبأن البيانات الواردة في طلب التمويل جزء لا يتجزأ من هذا العقد."),
    "amount": ("المادة 2 - قيمة التمويل والغرض",
               "يمنح المقرض المقترض تمويلاً بقيمة [المبلغ] لاستخدامه في أغراض شخصية، ولا يجوز استخدام التمويل في غير هذا الغرض. "
               "ويُضاف مبلغ التمويل إلى حساب المقترض لدى البنك بعد استيفاء جميع المستندات والضمانات المنصوص عليها في هذا العقد."),
    "rate": ("المادة 3 - العائد",
             "يُحتسب على رصيد التمويل القائم عائد متغير مرتبط بسعر الإقراض لليلة واحدة للبنك المركزي مضافاً إليه هامش قدره 2.5% سنوياً. "
             "ويُخطر المقرض المقترض كتابياً بأي تغيير في العائد قبل سريانه بخمسة عشر يوماً على الأقل."),
    "repayment": ("المادة 4 - السداد",
                  "يلتزم المقترض بسداد التمويل والعائد في صورة أقساط شهرية متساوية عددها [عدد الأقساط] قسطاً، ويستحق كل قسط في "
                  "اليوم الأول من كل شهر، ويُخصم القسط آلياً من حساب المقترض لدى البنك."),
    "prepayment": ("المادة 5 - السداد المعجل",
                   "يحق للمقترض السداد المعجل كلياً أو جزئياً في أي وقت بعد إخطار المقرض كتابياً، وتُستحق عمولة السداد المعجل بنسبة "
                   "1% من المبلغ المسدد مقدماً، ويُعاد جدولة الأقساط المتبقية أو تخفيض مدتها بناءً على اختيار المقترض."),
    "late": ("المادة 6 - التأخر في السداد",
             "إذا تأخر المقترض في سداد أي قسط لمدة تزيد على 90 يوماً من تاريخ استحقاقه، يحق للمقرض، بعد توجيه إنذار كتابي مدته 15 يوماً قبل اعتبار القرض حالاً، "
             "المطالبة بكامل الرصيد المتبقي. وتُحتسب على المبالغ المتأخرة غرامة تأخير لا تتجاوز 2% شهرياً على المبالغ المتأخرة."),
    "insurance": ("المادة 7 - التأمين",
                  "يكون التأمين على الحياة إلزامي طوال مدة التمويل لدى إحدى شركات التأمين المعتمدة، ويكون المستفيد من وثيقة التأمين "
                  "البنك بقدر الرصيد المستحق، ويُرد ما يزيد على ذلك إلى ورثة المقترض."),
    "security": ("المادة 8 - الضمانات",
                 "ضماناً للوفاء بالتزاماته، يلتزم المقترض بـتحويل الراتب إلى حساب لدى البنك طوال مدة التمويل، ولا يجوز له تحويل راتبه إلى "
                 "بنك آخر قبل السداد الكامل إلا بموافقة كتابية من المقرض."),
    "termination": ("المادة 9 - إنهاء العقد",
                    "يجوز للمقترض إنهاء العقد بإخطار كتابي مدته 30 يوماً بعد سداد كامل المستحقات. ويجوز للمقرض إنهاء العقد في حالات "
                    "الإخلال الجوهري بعد الإنذار، ومنها تقديم بيانات غير صحيحة أو التوقف عن السداد."),
    "liability": ("المادة 10 - حدود المسؤولية",
                  "لا يُسأل البنك عن الأضرار غير المباشرة التي قد تلحق بالمقترض نتيجة تنفيذ هذا العقد، وذلك فيما عدا حالات الغش أو الخطأ الجسيم "
                  "التي يُسأل عنها البنك وفقاً للقانون."),
    "data": ("المادة 11 - سرية البيانات",
             "يلتزم البنك بسرية بيانات المقترض وفق القانون رقم 194 لسنة 2020 (قانون البنك المركزي والجهاز المصرفي)، ولا تُشارك البيانات مع الغير إلا بموافقة "
             "المقترض أو بموجب القانون، وذلك فيما عدا الاستعلام الائتماني لدى الجهات المرخص لها."),
    "law": ("المادة 12 - القانون الواجب التطبيق والاختصاص",
            "يخضع هذا العقد ويُفسر وفقاً لأحكام القانون المصري، وتختص المحاكم الاقتصادية بالقاهرة بنظر أي نزاع ينشأ عن تنفيذ هذا العقد أو تفسيره."),
}

DEVIATIONS = {   # (contract, clause) -> replacement article text
    ("C01", "late"): ("المادة 6 - التأخر في السداد",
                      "إذا تأخر المقترض في سداد أي قسط لمدة تزيد على 60 يوماً من تاريخ استحقاقه، يحق للمقرض دون حاجة إلى إنذار أو حكم قضائي اعتبار القرض "
                      "حالاً والمطالبة بكامل الرصيد المتبقي، مع غرامة تأخير بنسبة 3% شهرياً على المبالغ المتأخرة."),
    ("C02", "prepayment"): ("المادة 5 - السداد المعجل",
                            "لا يحق للمقترض السداد المعجل خلال السنتين الأوليين من تاريخ العقد، ويجوز بعدها السداد المعجل بعد إخطار المقرض كتابياً، "
                            "وتُستحق عمولة السداد المعجل بنسبة 5% من المبلغ المسدد مقدماً."),
    ("C02", "insurance"): ("المادة 7 - التأمين",
                           "يكون التأمين على الحياة اختياري للمقترض، وفي حال إبرامه يكون المستفيد من الوثيقة ورثة المقترض."),
    ("C03", "law"): ("المادة 12 - القانون الواجب التطبيق والاختصاص",
                     "يخضع هذا العقد ويُفسر وفقاً لأحكام القانون الإنجليزي، ويُحال أي نزاع ينشأ عنه إلى التحكيم في لندن وفقاً لقواعد غرفة التحكيم المختارة."),
    ("C04", "liability"): ("المادة 10 - حدود المسؤولية",
                           "لا يُسأل البنك عن أي أضرار مباشرة أو غير مباشرة تلحق بالمقترض لأي سبب كان، ولا يوجد أي استثناء من هذا الإعفاء."),
    ("C04", "rate"): ("المادة 3 - العائد",
                      "يُحتسب على رصيد التمويل القائم عائد ثابت يحدده المقرض عند التعاقد، ويحق للبنك تعديل العائد في أي وقت دون إخطار المقترض."),
    ("C05", "data"): ("المادة 11 - سرية البيانات",
                      "يلتزم البنك بسرية بيانات المقترض، ومع ذلك يحق للبنك مشاركة بيانات المقترض مع شركاته التابعة وشركائه التسويقيين لأغراض "
                      "العروض والخدمات دون حاجة إلى موافقة إضافية."),
}


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
            body = body.replace("[اسم المقترض]", k["borrower"]).replace("[المبلغ]", k["amount"]).replace("[عدد الأقساط]", k["installments"])
            parts.append(article(title, body))
        (OUT / f"{k['id']}.md").write_text(
            f"# عقد تمويل رقم {k['id']}\n\nالمقترض: {k['borrower']} · قيمة التمويل: {k['amount']} · عدد الأقساط: {k['installments']}\n\n"
            "عقد تجريبي لأغراض العرض.\n\n" + "\n\n".join(parts) + "\n", encoding="utf-8")
        contracts.append({"file": f"{k['id']}.md", "borrower": k["borrower"], "deviations":
            [{"clause": d["clause"], "title": by_key[d["clause"]]["title"], "severity": d["severity"], "why_ar": d["why_ar"],
              "template_facts": by_key[d["clause"]]["facts"], "contract_facts": d["facts"]} for d in k["deviations"]] +
            [{"clause": m, "title": by_key[m]["title"], "severity": "high", "why_ar": "المادة محذوفة بالكامل من العقد",
              "template_facts": by_key[m]["facts"], "contract_facts": None} for m in k.get("missing", [])]})
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
