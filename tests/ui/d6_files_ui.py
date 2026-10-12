"""D6 file chat in the real portal (Playwright): upload progress, the file chips, a refused file, several files,
and the conversation coming back after a page reload.

    docker run --rm --network host -u pwuser -v $PWD/tests/ui:/tests:ro -v $PWD/test-cases/chat-files-test:/files:ro \
        -v $PWD/ops/ui:/out mcr.microsoft.com/playwright/python:v1.55.0-noble python /tests/d6_files_ui.py
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE, FILES, OUT = "http://localhost:8200", "/files", "/out"
# SECTIONS=6,7 runs only those parts (each starts its own chat)
SECTIONS = [int(n) for n in os.getenv("SECTIONS", "1,2,3,4,5,6,7,8,9,10,11").split(",")]
checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, note: str = "") -> None:
    checks.append((name, ok, note))
    print(f"  {'PASS' if ok else 'FAIL'} {name}  {note}", flush=True)


def watch_upload(page, shot: str | None = None) -> list[str]:
    """Texts the progress chip showed until it disappeared."""
    seen: list[str] = []
    page.wait_for_selector('[data-test="upload-progress"]', timeout=15000)
    t0 = time.time()
    while page.locator('[data-test="upload-progress"]').count() and time.time() - t0 < 300:
        try:
            text = " | ".join(page.locator('[data-test="upload-progress"]').all_inner_texts()).replace("\n", " ")
        except Exception:  # noqa: BLE001 - the chip can vanish between the count and the read
            break
        if text and (not seen or seen[-1] != text):
            seen.append(text)
            if shot and "of 10" in text and "page 4" in text:
                page.screenshot(path=f"{OUT}/{shot}")
        time.sleep(0.4)
    return seen


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(f"{BASE}/d6")

    if 1 in SECTIONS:
        print("1. progress while a 10-page scan is read")
        page.goto(f"{BASE}/d6")
        page.set_input_files('input[type="file"]', f"{FILES}/scanned_10_pages.pdf")
        seen = watch_upload(page, "d6-upload-progress.png")
        for s in seen:
            print("     ", s[:110])
        check("stages shown in order", any("converting" in s for s in seen) and any("reading page" in s for s in seen))
        check("page counter moves", len({s for s in seen if "reading page" in s}) >= 3, f"{len(seen)} different texts")
        check("time left shown", any("s left" in s for s in seen))
        chip = page.locator("text=scanned_10_pages.pdf").first
        check("file chip appears when done", chip.count() == 1 and "10 pages" in page.content())

    if 2 in SECTIONS:
        print("2. ask, then reload the page")
        page.fill("textarea", "What is the call centre number in this file?")
        page.keyboard.press("Enter")
        page.wait_for_selector('[data-test="answer"]', timeout=180000)
        answer = page.locator('[data-test="answer"]').first.inner_text()
        check("answer from the file", "19623" in answer, answer[:70].replace("\n", " "))
        page.reload()
        page.wait_for_selector('[data-test="answer"]', timeout=20000)
        check("conversation back after reload", "19623" in page.locator('[data-test="answer"]').first.inner_text())
        check("file chip back after reload", page.locator("text=scanned_10_pages.pdf").count() >= 1)

    if 3 in SECTIONS:
        print("3. cancel an upload")
        page.click("text=New chat")
        page.set_input_files('input[type="file"]', f"{FILES}/scanned_10_pages.pdf")
        page.wait_for_selector('[data-test="upload-progress"]', timeout=15000)
        time.sleep(3)
        page.click('[data-test="upload-progress"] button')
        time.sleep(2)
        check("cancelled upload leaves no chip", page.locator('[data-test="upload-progress"]').count() == 0 and page.locator("text=scanned_10_pages.pdf").count() == 0)

    if 4 in SECTIONS:
        print("4. a refused file")
        page.set_input_files('input[type="file"]', f"{FILES}/bad-uploads/protected.pdf")
        page.wait_for_selector("text=protected with a password", timeout=15000)
        check("refusal message shown", True, page.locator("text=protected with a password").first.inner_text()[:80])

    if 5 in SECTIONS:
        print("5. two files at once, one question across them")
        page.set_input_files('input[type="file"]', [f"{FILES}/multi/fees_2025.md", f"{FILES}/multi/fees_2026.md"])
        page.wait_for_selector("text=fees_2026.md", timeout=30000)
        page.wait_for_function("document.querySelectorAll('[data-test=\"upload-progress\"]').length === 0", timeout=30000)
        check("two file chips", page.locator("text=fees_2025.md").count() >= 1 and page.locator("text=fees_2026.md").count() >= 1)
        page.fill("textarea", "What is the debit card replacement fee?")
        page.keyboard.press("Enter")
        page.wait_for_selector('[data-test="answer"]', timeout=180000)
        answer = page.locator('[data-test="answer"]').last.inner_text()
        check("answer cites both files", "50" in answer and "75" in answer and "fees_2025" in answer and "fees_2026" in answer, answer[:90].replace("\n", " "))
        page.screenshot(path=f"{OUT}/d6-two-files.png")

    if 6 in SECTIONS:
        print("6. citations and the source panel")
        page.goto(f"{BASE}/d6")
        if page.locator("text=New chat").count():
            page.click("text=New chat")
        page.set_input_files('input[type="file"]', f"{FILES}/Reg_circular.pdf")
        page.wait_for_selector("text=Reg_circular.pdf", timeout=60000)
        page.wait_for_function("document.querySelectorAll('[data-test=\"upload-progress\"]').length === 0", timeout=60000)
        page.fill("textarea", "What is the mandatory deadline for Phase 3, Core IT Integration?")
        page.keyboard.press("Enter")
        page.wait_for_selector('[data-test="answer"]', timeout=180000)
        check("sources listed under the answer", page.locator('[data-test="source"]').count() >= 1, page.locator('[data-test="sources"]').first.inner_text()[:90].replace("\n", " "))
        cite = page.locator('[data-test="answer"] .md-body button').first
        check("citation mark in the answer text", cite.count() == 1, cite.inner_text() if cite.count() else "")
        (cite if cite.count() else page.locator('[data-test="source"]').first).click()
        page.wait_for_selector('[data-test="source-panel"]', timeout=5000)
        panel = page.locator('[data-test="source-panel"]').inner_text()
        check("source panel shows the passage", "2027" in panel and "Phase 3" in panel, panel[:80].replace("\n", " "))
        page.click('[data-test="show-page"]')
        page.wait_for_function("(() => { const i = document.querySelector('[data-test=\"source-page\"]'); return i && i.complete && i.naturalWidth > 0; })()", timeout=60000)
        check("page image loads", True)
        page.screenshot(path=f"{OUT}/d6-source-panel.png")
        page.keyboard.press("Escape")
        page.mouse.click(5, 5)

    if 7 in SECTIONS:
        print("7. Arabic portal")
        page.goto(f"{BASE}/d6?lang=ar")
        page.click("text=محادثة جديدة")
        page.set_input_files('input[type="file"]', f"{FILES}/test_cirular.pdf")
        seen = watch_upload(page)
        check("progress in Arabic", any("جارٍ قراءة الصفحة" in s for s in seen), (seen[-1] if seen else "")[:80])

    if 8 in SECTIONS:
        print("8. the draft card: options, what to fill in, edit, approve, revise, Word")
        page.goto(f"{BASE}/d6")
        if page.locator("text=New chat").count():
            page.click("text=New chat")
        page.click('[data-test="draft-options-toggle"]')
        page.wait_for_selector('[data-test="draft-options"]', timeout=10000)
        page.select_option('[data-test="draft-type"]', "letter")
        page.select_option('[data-test="draft-length"]', "short")
        page.fill("textarea", "Write a letter to a customer apologising for a delayed card delivery and offering to waive the issuance fee.")
        page.keyboard.press("Enter")
        page.wait_for_selector('[data-test="draft-card"]', timeout=240000)
        card = page.locator('[data-test="draft-card"]').last
        check("draft shown as a card with its subject", card.locator('[data-test="draft-subject"]').count() == 1, card.locator('[data-test="draft-subject"]').inner_text()[:60] if card.locator('[data-test="draft-subject"]').count() else "")
        box = card.locator('[data-test="draft-review"]')
        check("'Before sending' lists what to fill in", box.count() == 1 and "[" in box.inner_text(), box.inner_text()[:100].replace("\n", " ") if box.count() else "")
        check("Approve is disabled while something is open", card.locator('[data-test="draft-approve"]').is_disabled())
        page.screenshot(path=f"{OUT}/d6-draft-card.png")
        card.locator('[data-test="draft-edit-button"]').click()
        text = card.locator('[data-test="draft-edit"]').input_value()
        import re as _re
        card.locator('[data-test="draft-edit"]').fill(_re.sub(r"\[[^\]\n]+\]", "Mr. Ahmed Saad", text))
        card.locator('[data-test="draft-save"]').click()
        page.wait_for_selector('[data-test="draft-ready"]', timeout=30000)
        card = page.locator('[data-test="draft-card"]').last
        check("edited draft is read back and ready", "v2" in card.inner_text())
        card.locator('[data-test="draft-approve"]').click()
        page.wait_for_selector('[data-test="draft-approved"]', timeout=30000)
        check("approval recorded", True, page.locator('[data-test="draft-approved"]').inner_text()[:70])
        word = page.request.get(BASE + card.locator('[data-test="draft-word"]').get_attribute("href"))
        check("Word file downloads", word.ok and word.body()[:2] == b"PK", f"{len(word.body())} bytes")
        page.fill("textarea", "Make it shorter.")
        page.keyboard.press("Enter")
        page.wait_for_function("document.querySelectorAll('[data-test=\"draft-card\"]').length >= 2", timeout=240000)
        card = page.locator('[data-test="draft-card"]').last
        check("revision is a new version with its changes", card.locator('[data-test="show-changes"]').count() == 1, card.inner_text()[:60].replace("\n", " "))
        if card.locator('[data-test="show-changes"]').count():
            card.locator('[data-test="show-changes"]').check()
            check("changes are highlighted", card.locator("del").count() + card.locator("ins").count() > 0)
            page.screenshot(path=f"{OUT}/d6-draft-changes.png")

    if 9 in SECTIONS:
        print("9. summaries: an Arabic file as action items, the check box under it, a shorter version, Word")
        page.goto(f"{BASE}/d6?lang=ar")
        if page.locator("text=محادثة جديدة").count():
            page.click("text=محادثة جديدة")
        page.set_input_files('input[type="file"]', "/summaries/docs/meeting_ar.txt")
        page.wait_for_selector("text=meeting_ar.txt", timeout=60000)
        page.wait_for_function("document.querySelectorAll('[data-test=\"upload-progress\"]').length === 0", timeout=60000)
        page.click('[data-test="summary-options-toggle"]')
        page.wait_for_selector('[data-test="summary-options"]', timeout=10000)
        page.select_option('[data-test="summary-form"]', "actions")
        page.fill("textarea", "لخّص هذا المحضر.")
        page.keyboard.press("Enter")
        page.wait_for_selector('[data-test="summary-tools"]', timeout=240000)
        answer = page.locator('[data-test="answer"]').last
        check("action items shown as a table", answer.locator("table").count() >= 1 and "منى" in answer.inner_text())
        tools = page.locator('[data-test="summary-tools"]').last
        check("coverage and check result shown", "المصدر" in tools.locator('[data-test="summary-coverage"]').inner_text(), tools.locator('[data-test="summary-coverage"]').inner_text()[:70])
        check("sources listed", answer.locator('[data-test="source"]').count() >= 1)
        page.screenshot(path=f"{OUT}/d6-summary.png", full_page=True)
        with page.expect_download(timeout=30000) as dl:
            tools.locator('[data-test="summary-word"]').click()
        check("Word file downloads", dl.value.suggested_filename.endswith(".docx"))
        before = len(answer.inner_text())
        tools.locator('[data-test="summary-shorter"]').click()
        page.wait_for_function("document.querySelectorAll('[data-test=\"summary-tools\"]').length >= 2", timeout=240000)
        check("'Shorter' gives a shorter summary", len(page.locator('[data-test="answer"]').last.inner_text()) < before)

    if 10 in SECTIONS:
        print("10. translation: an Arabic file into English, the status line, side by side, Word")
        page.goto(f"{BASE}/d6")
        if page.locator("text=New chat").count():
            page.click("text=New chat")
        page.set_input_files('input[type="file"]', "/summaries/docs/thread_ar.txt")
        page.wait_for_selector("text=thread_ar.txt", timeout=60000)
        page.wait_for_function("document.querySelectorAll('[data-test=\"upload-progress\"]').length === 0", timeout=60000)
        page.fill("textarea", "ترجم هذا الملف إلى الإنجليزية.")
        page.keyboard.press("Enter")
        page.wait_for_selector('[data-test="translation-view"]', timeout=240000)
        view = page.locator('[data-test="translation-view"]').last
        status = view.locator('[data-test="translation-status"]').inner_text()
        check("status line says how much was translated", "paragraphs translated" in status, status[:90])
        answer = page.locator('[data-test="answer"]').last.inner_text()
        check("translation is English and keeps the references", "DSP-88214" in answer and "4,750" in answer)
        if not view.locator('[data-test="translation-side"]').is_checked():
            view.locator('[data-test="translation-side"]').check()
        rows = view.locator('[data-test="translation-table"] tbody tr').count()
        check("source and translation side by side", rows >= 8, f"{rows} rows")
        page.screenshot(path=f"{OUT}/d6-translation.png", full_page=True)
        with page.expect_download(timeout=30000) as dl:
            view.locator('[data-test="translation-bilingual"]').click()
        check("two-column Word file downloads", dl.value.suggested_filename.endswith(".docx"))

    if 11 in SECTIONS:
        print("11. code: written for an attached workbook and run on it; a risky query flagged; the suggested requests")
        page.goto(f"{BASE}/d6")
        if page.locator("text=New chat").count():
            page.click("text=New chat")
        page.set_input_files('input[type="file"]', f"{FILES}/branch_loans.xlsx")
        page.wait_for_selector("text=branch_loans.xlsx", timeout=60000)
        page.wait_for_function("document.querySelectorAll('[data-test=\"upload-progress\"]').length === 0", timeout=60000)
        page.fill("textarea", "Write pandas code that prints the total amount of Approved loans for the Giza branch.")
        page.keyboard.press("Enter")
        page.wait_for_selector('[data-test="code-note"]', timeout=240000)
        note = page.locator('[data-test="code-note"]').last
        ran = note.locator('[data-test="code-ran"]').inner_text() if note.locator('[data-test="code-ran"]').count() else ""
        check("note says the code was run on the file", "Run on branch_loans.xlsx" in ran, ran[:90])
        answer = page.locator('[data-test="answer"]').last.inner_text()
        check("the result shown is the true figure", "1054000" in answer.replace(",", ""))
        page.screenshot(path=f"{OUT}/d6-code-run.png", full_page=True)
        page.click("text=New chat")
        page.fill("textarea", "Explain this code:\n```python\nquery = \"SELECT * FROM customers WHERE national_id = '\" + user_input + \"'\"\ncursor.execute(query)\n```")
        page.keyboard.press("Enter")
        page.wait_for_selector('[data-test="code-warning"]', timeout=240000)
        warning = page.locator('[data-test="code-warning"]').last.inner_text()
        check("injection risk flagged under the answer", "injection" in warning.lower(), warning[:90])
        check("no code options button in the bar", page.locator('[data-test="code-options-toggle"]').count() == 0)
        page.click("text=New chat")
        chips = page.locator('[data-test="suggested"]')
        check("eight suggested requests, six with a sample file", chips.count() == 8 and page.locator('[data-test="suggested"]:has-text("📎")').count() == 6, f"{chips.count()} chips")
        page.locator('[data-test="suggested"]:has-text("complaints_ar.csv")').click()
        page.wait_for_selector('[data-test="code-ran"]', timeout=240000)
        answer = page.locator('[data-test="answer"]').last.inner_text()
        check("a suggested request attaches its sample and runs the code on it", "complaints_ar.csv" in page.content() and "9.66" in answer, answer[-80:].replace("\n", " "))
        page.screenshot(path=f"{OUT}/d6-code-warning.png", full_page=True)

    browser.close()

failed = [c for c in checks if not c[1]]
print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
sys.exit(1 if failed else 0)
