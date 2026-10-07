"""Scripted walkthrough of every live demo in the real portal (Playwright, in a container).

    python walkthrough.py [--base http://localhost:8200] [--lang ar|en] [--record] [--only d2,d5] [--out /out]

Each scenario performs the demo's core action, waits for the real result (real models, no mocks)
and saves a screenshot. With --record it also saves a video per demo: these are the backup videos
PLAN.md requires for live-failure insurance (`make record`).
"""
import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

TIMEOUT = 240_000


def d1(p: Page) -> None:
    p.get_by_role("button", name="A01").first.click()
    p.get_by_text("A01").first.wait_for()
    p.get_by_role("button", name="Verify").or_(p.get_by_role("button", name="تحقق")).first.click()
    p.locator("[data-test=verdict]").wait_for(timeout=TIMEOUT)


def d2(p: Page) -> None:
    p.locator("[data-test=suggested]").first.click()
    p.locator("[data-test=answer]").first.wait_for(timeout=TIMEOUT)


def d3(p: Page) -> None:
    p.locator("[data-test=run-campaign]").click()
    p.locator("[data-test=campaign-card]").wait_for(timeout=TIMEOUT)


def d4(p: Page) -> None:
    p.locator("[data-test=script-step]").first.click()
    p.locator("[data-test=agent-reply]").first.wait_for(timeout=TIMEOUT)


def d5(p: Page) -> None:
    p.locator("select").first.select_option("C01.md")
    p.locator("[data-test=analyze]").click()
    p.locator("[data-test=risk-flags]").wait_for(timeout=TIMEOUT)


def d6(p: Page) -> None:
    p.locator("[data-test=suggested]").first.click()
    p.locator("[data-test=answer]").first.wait_for(timeout=TIMEOUT)


def d7(p: Page) -> None:
    p.locator("[data-test=queue-item]").first.click()
    btn = p.locator("[data-test=triage]")
    if btn.count():
        btn.click()
    p.locator("[data-test=draft]").wait_for(timeout=TIMEOUT)


SCENARIOS = {"d1": d1, "d2": d2, "d3": d3, "d4": d4, "d5": d5, "d6": d6, "d7": d7}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8200")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default="/out")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    only = a.only.split(",") if a.only else list(SCENARIOS)
    failed = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for demo in only:
            ctx = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="ar-EG" if a.lang == "ar" else "en-US",
                                      record_video_dir=str(out / "video") if a.record else None,
                                      record_video_size={"width": 1440, "height": 1000})
            page = ctx.new_page()
            t = time.time()
            try:
                page.goto(f"{a.base}/{demo}?lang={a.lang}", wait_until="networkidle")
                SCENARIOS[demo](page)
                page.wait_for_timeout(1500)
                page.screenshot(path=str(out / f"{demo}_{a.lang}.png"), full_page=True)
                print(f"PASS {demo} ({time.time() - t:.0f}s)", flush=True)
            except Exception as exc:  # noqa: BLE001
                page.screenshot(path=str(out / f"{demo}_{a.lang}_FAIL.png"), full_page=True)
                print(f"FAIL {demo}: {type(exc).__name__}: {str(exc).splitlines()[0]}", flush=True)
                failed.append(demo)
            video = page.video
            ctx.close()
            if a.record and video:
                Path(video.path()).rename(out / "video" / f"{demo}_{a.lang}.webm")
        browser.close()
    print(f"walkthrough: {len(only) - len(failed)}/{len(only)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
