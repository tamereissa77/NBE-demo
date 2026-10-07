"""Capture the screenshots for the demo guide: every scenario, real models, real UI.
    python capture_guide.py [--base http://localhost:8200] [--out /out]
Run after `make demo-reset`. Takes ~6 minutes (D7 triage and D3 generation dominate).
"""
import argparse
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

T = 300_000
ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://localhost:8200")
ap.add_argument("--out", default="/out")
ap.add_argument("--only", default="", help="comma list: home,d1,...,d7,eval")
a = ap.parse_args()
OUT = Path(a.out)
OUT.mkdir(parents=True, exist_ok=True)
ONLY = set(a.only.split(",")) if a.only else None
want = lambda k: ONLY is None or k in ONLY  # noqa: E731


def shot(p: Page, name: str, target=None, full=False):
    p.wait_for_timeout(700)
    path = str(OUT / f"{name}.png")
    if target is not None:
        target.scroll_into_view_if_needed()
        target.screenshot(path=path)
    else:
        p.screenshot(path=path, full_page=full)
    print("saved", name, flush=True)


def workspace(p: Page):
    return p.locator("main > div > div.mt-5").first


def go(p: Page, path: str, lang="en"):
    p.goto(f"{a.base}{path}{'&' if '?' in path else '?'}lang={lang}", wait_until="networkidle")


with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=1.25)
    p = ctx.new_page()

    if want('home'):
        # Landing page, both languages
        go(p, "/")
        shot(p, "00_home_en")
        go(p, "/", "ar")
        shot(p, "00_home_ar")

    if want('d2'):
        # D2: cited answer + version delta, citation viewer, dialect, not found, trace
        go(p, "/d2")
        p.locator("[data-test=suggested]").first.click()
        p.locator("[data-test=answer]").first.wait_for(timeout=T)
        shot(p, "d2_1_cited_answer", workspace(p))
        p.locator("[data-test=answer] button").first.click()
        p.get_by_role("button", name="Close").wait_for()
        shot(p, "d2_2_citation_viewer")
        p.get_by_role("button", name="Close").click()
        p.locator("form input").fill("لو العميل يبي يرفع حد التحويل لـ 150 ألف، وش يسوي؟")
        p.locator("form button[type=submit]").click()
        p.locator("[data-test=answer]").nth(1).wait_for(timeout=T)
        p.locator("form input").fill("هل يمكن إرسال البطاقة البديلة إلى منزل العميل بالبريد؟")
        p.locator("form button[type=submit]").click()
        p.locator("[data-test=answer]").nth(2).wait_for(timeout=T)
        shot(p, "d2_3_dialect_and_not_found", workspace(p))
        p.locator("details summary").filter(has_text="Show the work").click()
        shot(p, "d2_4_show_the_work", p.locator("details").filter(has_text="Show the work").first)

    if want('d1'):
        # D1: forged pack A01, evidence viewer, ELA; clean pack A04 with planned false positive + decision
        go(p, "/d1")
        p.locator("[data-test=pack]").first.click()
        p.locator("[data-test=verify]").click()
        p.locator("[data-test=verdict]").wait_for(timeout=T)
        shot(p, "d1_1_A01_flagged", workspace(p))
        p.locator("button:has(img[alt=hr_letter])").click()
        p.get_by_role("button", name="Close").wait_for()
        shot(p, "d1_2_evidence_viewer")
        p.get_by_role("button", name="ELA heatmap").click()
        shot(p, "d1_3_ela_heatmap")
        p.get_by_role("button", name="Extracted fields").click()
        shot(p, "d1_4_extracted_fields")
        p.get_by_role("button", name="Close").click()
        p.locator("[data-test=pack]").nth(3).click()
        p.locator("[data-test=verify]").click()
        p.locator("[data-test=verdict]").wait_for(timeout=T)
        p.locator("textarea").fill("Phone re-scan of a genuine bill; original seen at branch.")
        p.get_by_role("button", name="Documents OK").click()
        p.get_by_text("Decision recorded").wait_for()
        shot(p, "d1_5_A04_cleared", workspace(p))

    if want('d7'):
        # D7: queue after triage, detail with draft, approve, trends, accuracy
        go(p, "/d7")
        p.get_by_role("button", name="Triage all").click()
        p.locator("[data-test=queue-item]").filter(has_text="S4").first.wait_for(timeout=T)
        p.wait_for_function("() => !document.body.innerText.includes('Classifying, routing')", timeout=T)
        p.locator("[data-test=queue-item]").filter(has_text="S4").first.click()
        p.locator("[data-test=draft]").wait_for()
        shot(p, "d7_1_queue_and_draft", workspace(p))
        p.get_by_role("button", name="Approve & send").click()
        p.wait_for_timeout(1500)
        shot(p, "d7_2_approved", p.locator("section").filter(has_text="Triage dashboard").last)
        p.get_by_role("button", name="Trends").click()
        p.get_by_text("themes found by clustering").wait_for(timeout=T)
        shot(p, "d7_3_trends", workspace(p))
        p.get_by_role("button", name="Accuracy").click()
        p.get_by_text("Topic accuracy").wait_for(timeout=T)
        shot(p, "d7_4_accuracy", workspace(p))

    if want('d3'):
        # D3: campaign with stress test (planted banned claim caught), banner, A/B plan
        go(p, "/d3")
        p.get_by_label("Stress-test compliance (plant a banned claim)").check()
        p.locator("[data-test=run-campaign]").click()
        p.locator("[data-test=campaign-card]").wait_for(timeout=T)
        shot(p, "d3_1_profile_and_card", workspace(p))
        shot(p, "d3_2_banner", p.locator("img[alt=banner]").locator(".."))
        shot(p, "d3_3_ab_plan", p.locator("div").filter(has_text="A/B test plan").last)

    if want('d4'):
        # D4: the full script (lost card, code, block, complaint, jailbreak, human)
        go(p, "/d4")
        steps = p.locator("[data-test=script-step]")
        for i in range(6):
            if i == 1:
                p.get_by_text("Say the code").wait_for(timeout=T)
            steps.nth(i).click()
            p.locator("[data-test=agent-reply]").nth(i).wait_for(timeout=T)
            if i == 2:
                shot(p, "d4_1_otp_verified_card_blocked", workspace(p))
        shot(p, "d4_2_complaint_jailbreak_handoff", workspace(p))

    if want('d5'):
        # D5: contract C01, diff modal, ruling R02
        go(p, "/d5")
        p.locator("select").first.select_option("C01.md")
        p.locator("[data-test=analyze]").click()
        p.locator("[data-test=risk-flags]").wait_for(timeout=T)
        shot(p, "d5_1_contract_C01", workspace(p))
        p.locator("button").filter(has_text="التأخر في السداد").first.click()
        p.get_by_role("button", name="Close").wait_for()
        shot(p, "d5_2_template_diff")
        p.get_by_role("button", name="Close").click()
        p.locator("select").first.select_option("R02.md")
        p.locator("[data-test=analyze]").click()
        p.get_by_text("حكم").first.wait_for(timeout=T)
        p.wait_for_timeout(1500)
        shot(p, "d5_3_ruling_R02", p.locator("section").filter(has_text="Legal summary card").last)

    if want('d6'):
        # D6: translation, drafting, code with routing panel
        go(p, "/d6")
        for i in (1, 3):
            p.locator("[data-test=suggested]").nth(i).click()
            p.locator("[data-test=answer]").first.wait_for(timeout=T)
            shot(p, f"d6_{i}", workspace(p))
            go(p, "/d6")

    if want('eval'):
        # Arabic gate
        go(p, "/eval?scorer=guide-preview")
        p.get_by_text("Cited answer from the current procedure").wait_for(timeout=T)
        shot(p, "eval_1_scoring")
        go(p, "/eval/results")
        p.get_by_text("Recommendation").wait_for(timeout=T)
        shot(p, "eval_2_results")
    b.close()
