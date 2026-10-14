"""Record the CDM demo video: the real portal in a real (headed) Chromium on a virtual display, captured by ffmpeg.
    python film.py --rehearse    screenshots at each caption, no capture, no waiting for the voice
    python film.py               the real take: /w/out/raw.mkv + /w/out/events.json
"""
import base64, json, os, re, subprocess, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright, Page

sys.path.insert(0, "/w")
from lines import L

B = "http://localhost:8200"
T = 400_000
REH = "--rehearse" in sys.argv
ONLY = next((a.split("=", 1)[1].split(",") for a in sys.argv if a.startswith("--only=")), None)
OUT = Path("/w/out"); OUT.mkdir(exist_ok=True)
DUR = {k: v["dur"] for k, v in json.load(open("/w/tts/index.json")).items()}
THEME = dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})", open("/repo/brand/theme.css").read()))
LOGO = base64.b64encode(open("/repo/brand/logo-full.png", "rb").read()).decode()
BRAND, ACCENT, DARK = THEME["brand"], THEME["accent"], THEME["brand-dark"]

OVERLAY = """
(() => {
  const build = () => {
    if (document.getElementById('__cap')) return;
    const st = document.createElement('style');
    st.textContent = `
      #__cap{position:fixed;left:50%;bottom:26px;transform:translateX(-50%) translateY(12px);max-width:1360px;width:max-content;
        background:rgba(12,18,32,.88);color:#fff;border-radius:14px;padding:14px 30px 12px;z-index:2147483646;opacity:0;
        transition:opacity .35s, transform .35s;text-align:center;box-shadow:0 10px 40px rgba(0,0,0,.35);border-top:4px solid ACCENT;pointer-events:none}
      #__cap.on{opacity:1;transform:translateX(-50%) translateY(0)}
      #__cap .ar{font:600 27px/1.55 "Cairo","Noto Sans Arabic",sans-serif;direction:rtl}
      #__cap .en{font:400 16px/1.4 "Inter","Noto Sans",sans-serif;opacity:.78;margin-top:4px;direction:ltr}
      #__cur{position:fixed;left:-60px;top:-60px;width:30px;height:30px;z-index:2147483647;pointer-events:none;
        transition:left .75s cubic-bezier(.4,.1,.2,1), top .75s cubic-bezier(.4,.1,.2,1);filter:drop-shadow(0 2px 3px rgba(0,0,0,.45))}
      .__rip{position:fixed;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;border:3px solid ACCENT;z-index:2147483646;
        pointer-events:none;animation:__rip .6s ease-out forwards}
      @keyframes __rip{to{transform:scale(4);opacity:0}}
      #__badge{position:fixed;top:96px;left:50%;transform:translateX(-50%);background:BRAND;color:#fff;border-radius:99px;padding:8px 20px;
        font:600 18px "Cairo","Noto Sans Arabic",sans-serif;z-index:2147483646;display:none;direction:rtl;box-shadow:0 6px 24px rgba(0,0,0,.25)}
      #__badge b{font-variant-numeric:tabular-nums;direction:ltr;display:inline-block;margin-inline-start:8px;color:ACCENT_LIGHT}
      ::-webkit-scrollbar{width:0;height:0}
    `;
    document.documentElement.appendChild(st);
    const cap = document.createElement('div'); cap.id = '__cap'; cap.innerHTML = '<div class="ar"></div><div class="en"></div>';
    const cur = document.createElement('div'); cur.id = '__cur';
    cur.innerHTML = '<svg viewBox="0 0 24 24" width="30" height="30"><path d="M4 2l15 11-6.5 1.2 3.8 7.3-2.6 1.3-3.8-7.3L5 20z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    const badge = document.createElement('div'); badge.id = '__badge';
    document.documentElement.append(cap, cur, badge);
    const p = JSON.parse(sessionStorage.getItem('__curpos') || '[960,620]');
    cur.style.transition = 'none'; cur.style.left = p[0] + 'px'; cur.style.top = p[1] + 'px';
    requestAnimationFrame(() => requestAnimationFrame(() => cur.style.transition = ''));
  };
  window.__cap = (ar, en) => { build(); const c = document.getElementById('__cap'); c.querySelector('.ar').textContent = ar; c.querySelector('.en').textContent = en; c.classList.add('on'); };
  window.__capOff = () => { const c = document.getElementById('__cap'); c && c.classList.remove('on'); };
  window.__move = (x, y) => { build(); const c = document.getElementById('__cur'); c.style.left = x + 'px'; c.style.top = y + 'px'; sessionStorage.setItem('__curpos', JSON.stringify([x, y])); };
  window.__ripple = (x, y) => { const r = document.createElement('div'); r.className = '__rip'; r.style.left = x + 'px'; r.style.top = y + 'px'; document.documentElement.appendChild(r); setTimeout(() => r.remove(), 700); };
  window.__badgeOn = (label) => { build(); const b = document.getElementById('__badge'); const t0 = Date.now();
    b.innerHTML = '⏩ ' + label + ' · الزمن الفعلي <b>0:00</b>'; b.style.display = 'block';
    clearInterval(window.__bt); window.__bt = setInterval(() => { const s = Math.round((Date.now() - t0) / 1000);
      b.querySelector('b').textContent = Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }, 200); };
  window.__badgeOff = () => { clearInterval(window.__bt); const b = document.getElementById('__badge'); if (b) b.style.display = 'none'; };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build); else build();
})();
""".replace("ACCENT_LIGHT", THEME.get("accent-light", "#fff")).replace("ACCENT", ACCENT).replace("BRAND", BRAND)


class Film:
    def __init__(self, page: Page, t0: float):
        self.p, self.t0, self.ev, self.n = page, t0, [], 0

    def now(self):
        return round(time.time() - self.t0, 3)

    def log(self, *a):
        print(f"[{self.now():7.1f}]", *a, flush=True)

    def say(self, key, extra=0.6):
        ar, en, _ = L[key]
        self.p.evaluate("([a, e]) => window.__cap(a, e)", [ar, en])
        self.ev.append({"t": self.now(), "clip": key, "dur": DUR[key]})
        self.log("say", key)
        if REH:
            self.n += 1; self.p.wait_for_timeout(700); self.p.screenshot(path=str(OUT / f"r{self.n:02d}_{key}.png"))
        else:
            self.p.wait_for_timeout(int((DUR[key] + extra) * 1000))

    def off(self, pause=300):
        self.p.evaluate("window.__capOff && window.__capOff()"); self.p.wait_for_timeout(pause)

    def pause(self, s):
        self.p.wait_for_timeout(int(s * (0.2 if REH else 1) * 1000))

    def show(self, loc, block="center", wait=900):
        """Smooth-scroll an element into view."""
        try:
            loc.first.evaluate(f"e => e.scrollIntoView({{behavior: 'smooth', block: '{block}'}})")
            self.p.wait_for_timeout(wait)
        except Exception as e:
            self.log("show failed", str(e).splitlines()[0][:120])

    def top(self):
        self.p.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})"); self.p.wait_for_timeout(700)

    def click(self, loc, scroll=True):
        loc = loc.first
        if scroll:
            self.show(loc, wait=700)
        box = loc.bounding_box()
        if box:
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            self.p.evaluate("([x, y]) => window.__move(x, y)", [x, y]); self.p.wait_for_timeout(850)
            self.p.evaluate("([x, y]) => window.__ripple(x, y)", [x, y]); self.p.wait_for_timeout(150)
        loc.click()

    def fast(self, wait_fn, label="النموذج يعمل على الجهاز"):
        """A model at work: shown with a live 'real time' badge, sped up in the edit."""
        self.p.evaluate("l => window.__badgeOn(l)", label)
        a = self.now()
        try:
            wait_fn()
        finally:
            b = self.now()
            self.p.wait_for_timeout(300)
            self.p.evaluate("window.__badgeOff()")
        if b - a > 2.5:
            self.ev.append({"fast": [a, b]})
        self.log(f"fast {b - a:.0f}s")

    def go(self, path):
        self.p.goto(f"{B}{path}{'&' if '?' in path else '?'}lang=ar", wait_until="networkidle"); self.p.wait_for_timeout(600)

    def card(self, num, title_ar, title_en, sub_ar=""):
        """Full-screen title card in CDM colours."""
        html = f"""<html dir="rtl"><head><style>
          body{{margin:0;height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;
            background:linear-gradient(135deg,{BRAND} 0%,{DARK} 100%);color:#fff;font-family:"Cairo","Noto Sans Arabic",sans-serif;overflow:hidden}}
          .logo{{background:#fff;border-radius:18px;padding:18px 30px;margin-bottom:42px;box-shadow:0 12px 40px rgba(0,0,0,.25)}}
          .logo img{{height:{90 if num == '' else 64}px;display:block}}
          .num{{font:700 22px "Noto Sans",sans-serif;letter-spacing:4px;color:{ACCENT};background:#fff;border-radius:8px;padding:4px 16px;margin-bottom:22px}}
          h1{{font-size:{58 if num == '' else 64}px;margin:0;font-weight:800;text-align:center;line-height:1.35;max-width:1300px}}
          h2{{font:400 26px "Noto Sans",sans-serif;margin:16px 0 0;opacity:.85;direction:ltr}}
          .sub{{font-size:24px;margin-top:22px;opacity:.9;text-align:center;max-width:1200px}}
          .bar{{position:fixed;bottom:0;left:0;right:0;height:10px;background:{ACCENT}}}
          .gb{{position:fixed;bottom:34px;font:400 18px "Noto Sans",sans-serif;opacity:.75;direction:ltr}}
          .in{{animation:in .8s ease-out both}} @keyframes in{{from{{opacity:0;transform:translateY(18px)}}}}
        </style></head><body><div class="in" style="display:flex;flex-direction:column;align-items:center">
          <div class="logo"><img src="data:image/png;base64,{LOGO}"></div>
          {f'<div class="num">D{num}</div>' if num else ''}<h1>{title_ar}</h1><h2>{title_en}</h2>
          {f'<div class="sub">{sub_ar}</div>' if sub_ar else ''}</div>
          <div class="gb">Dell Pro Max with GB10 · offline · synthetic data</div><div class="bar"></div></body></html>"""
        self.p.set_content(html); self.p.evaluate(OVERLAY)
        self.p.wait_for_timeout(600 if REH else 2600)


def safe(f: Film, name, fn):
    try:
        fn()
    except Exception as e:
        f.log(f"!! {name}: {type(e).__name__}: {str(e).splitlines()[0][:200]}")
        if REH:
            f.p.screenshot(path=str(OUT / f"FAIL_{name}.png"))


def close_modal(f: Film):
    p = f.p
    p.keyboard.press("Escape"); p.wait_for_timeout(500)
    x = p.locator("[role=dialog] button, .fixed button").filter(has_text=re.compile(r"^\s*[×✕]\s*$|إغلاق|Close"))
    if x.count() and x.first.is_visible():
        f.click(x, scroll=False); p.wait_for_timeout(600)


def ask(f: Film, q: str):
    p = f.p
    box = p.locator("form input").first
    f.click(box, scroll=False)
    box.type(q, delay=30)
    f.click(p.locator("form button[type=submit]"), scroll=False)


# ------------------------------------------------------------------ the scenes
def intro(f: Film):
    f.card("", "الذكاء الاصطناعي لمصرف المغرب", "AI for Crédit du Maroc", "سبع حالات استخدام · جهاز واحد · دون إنترنت")
    f.say("intro1"); f.say("intro2"); f.off()
    f.go("/")
    f.p.mouse.move(960, 540)
    f.say("home")
    f.show(f.p.locator("text=D7").first, wait=1400); f.pause(1.5); f.top(); f.off()


def d1(f: Film):
    p = f.p
    f.card("1", "التحقق من مستندات الإقراض", "Doc verification for credit lending")
    f.go("/d1")
    f.click(p.locator("[data-test=mode-packs]"))
    f.click(p.locator("[data-test=pack]").first)
    f.say("d1a")
    f.click(p.locator("[data-test=verify]"))
    f.say("d1b")
    f.fast(lambda: p.locator("[data-test=verdict]").wait_for(timeout=T), "قراءة المستندات وفحصها على الجهاز")
    f.show(p.get_by_text("لوحة قرار المراجعة"), block="start")
    f.say("d1c"); f.off()

    def evidence():
        f.click(p.locator("button").filter(has_text="خطاب جهة العمل").first)
        p.wait_for_timeout(1500)
        f.say("d1d")
        f.click(p.get_by_role("button", name="خريطة مستوى الخطأ"), scroll=False)
        p.wait_for_timeout(1200); f.say("d1e")
        f.click(p.get_by_role("button", name="البيانات المستخرجة"), scroll=False)
        p.wait_for_timeout(1200); f.say("d1f"); f.off()
        close_modal(f)
    safe(f, "d1 evidence", evidence)

    def decide():
        f.click(p.locator("textarea").first)
        p.locator("textarea").first.type("الراتب غير مطابق لكشف الحساب: طلب شهادة أجر أصلية.", delay=35)
        f.click(p.get_by_role("button", name="طلب مستندات إضافية"))
        p.get_by_text("تم تسجيل القرار").first.wait_for(timeout=15000)
        f.say("d1g"); f.off()
    safe(f, "d1 decide", decide)


def d2(f: Film):
    p = f.p
    f.card("2", "المحادثة مع المستندات", "Chat with Document")
    f.go("/d2")
    f.click(p.locator("[data-test=suggested]").nth(0))
    f.say("d2a")
    f.fast(lambda: p.locator("[data-test=answer]").nth(0).wait_for(timeout=T), "البحث في المساطر والإجابة")
    p.wait_for_timeout(1200)
    f.say("d2b"); f.off()

    ask(f, "إلا بغا الزبون يرفع حد التحويل لـ 150 ألف، شنو خاصو يدير؟")
    f.fast(lambda: p.locator("[data-test=answer]").nth(1).wait_for(timeout=T), "البحث في المساطر والإجابة")
    p.wait_for_timeout(800); f.show(p.locator("[data-test=answer]").nth(1))
    f.say("d2d"); f.off()
    ask(f, "هل يمكن إرسال البطاقة البديلة إلى منزل الزبون بالبريد؟")
    f.fast(lambda: p.locator("[data-test=answer]").nth(2).wait_for(timeout=T), "البحث في المساطر والإجابة")
    p.wait_for_timeout(800); f.show(p.locator("[data-test=answer]").nth(2))
    f.say("d2e"); f.off()

    def work():
        f.click(p.locator("details summary").filter(has_text="اعرض التفاصيل"))
        p.wait_for_timeout(1000); f.show(p.locator("details").filter(has_text="اعرض التفاصيل").first, block="start")
        f.say("d2f"); f.off()
    safe(f, "d2 work", work)


def d3(f: Film):
    p = f.p
    f.card("3", "الحملات والعروض المخصّصة", "Campaigns & Offers")
    f.go("/d3")
    f.click(p.locator("select").first); p.locator("select").first.select_option("young_professional"); p.wait_for_timeout(600)
    f.click(p.get_by_label(re.compile("اختبار الامتثال")))
    f.say("d3a")
    f.click(p.locator("[data-test=run-campaign]"))
    f.say("d3b")
    f.fast(lambda: p.locator("[data-test=campaign-card]").wait_for(timeout=T), "تحليل وكتابة وتوليد الإعلان على الجهاز")
    p.wait_for_timeout(1000)
    f.show(p.get_by_text("ملف الاهتمامات").first, block="start")
    f.say("d3c")
    f.show(p.locator("[data-test=campaign-card]"), block="start")
    f.say("d3d"); f.off()

    def social():
        f.click(p.locator("button").filter(has_text=re.compile(r"^Social")))
        p.wait_for_timeout(900); f.say("d3e"); f.off()
    safe(f, "d3 social", social)
    f.show(p.locator("img[alt=banner]"), block="center", wait=1400)
    f.say("d3f")
    f.show(p.get_by_text("خطة اختبار A/B").first, block="start", wait=1200)
    f.say("d3g"); f.off()


def d4(f: Film):
    p = f.p
    f.card("4", "المساعد الافتراضي الذكي", "AI Virtual Agent")
    f.go("/d4")
    f.show(p.locator("[data-test=script-step]").first, block="start")
    f.say("d4a")
    steps = p.locator("[data-test=script-step]")
    keys = ["d4b", "d4c", "d4d", "d4e", "d4f", "d4g"]
    for i, k in enumerate(keys):
        def one(i=i, k=k):
            if i == 1:
                p.get_by_text("Say the code").or_(p.locator("[data-test=keypad]")).first.wait_for(timeout=T)
            f.click(steps.nth(i), scroll=False)
            f.fast(lambda: p.locator("[data-test=agent-reply]").nth(i).wait_for(timeout=T), "المساعد يجيب")
            p.wait_for_timeout(1300)
            f.say(k)
            if i == 2:
                f.show(p.get_by_text("مسار الإجراءات").first, wait=1200); f.pause(2.5)
                f.show(steps.first, block="start")
        safe(f, f"d4 step {i + 1}", one)
    f.off()


def d5(f: Film):
    p = f.p
    f.card("5", "تلخيص المستندات القانونية", "Legal Documents Summarisation")
    f.go("/d5")
    f.click(p.locator("select").first); p.locator("select").first.select_option("C01.md"); p.wait_for_timeout(500)
    f.click(p.locator("[data-test=analyze]"))
    f.say("d5a")
    f.fast(lambda: p.locator("[data-test=risk-flags]").wait_for(timeout=T), "التلخيص على مراحل")
    p.wait_for_timeout(1000)
    f.show(p.get_by_text("البنود").first, block="start", wait=1200)
    f.say("d5b")
    f.show(p.get_by_text("المقارنة بالنموذج المعتمد").first, block="start", wait=1200)
    f.say("d5c"); f.off()
    f.top()
    f.click(p.locator("select").first); p.locator("select").first.select_option("R02.md"); p.wait_for_timeout(500)
    f.click(p.locator("[data-test=analyze]"))
    f.say("d5d")
    f.fast(lambda: p.locator("[data-test=ruling]").or_(p.locator("[data-test=award-split]")).first.wait_for(timeout=T), "تلخيص الحكم")
    p.wait_for_timeout(1500)
    f.show(p.locator("[data-test=ruling]").first, block="start")
    f.say("d5e"); f.off()


def d6(f: Film):
    p = f.p
    f.card("6", "المساعد الذكي لمصرف المغرب", "CDM AI Assistant")
    for n, (idx, keys) in enumerate([(4, ["d6a", "d6b"]), (0, ["d6c"]), (3, ["d6d"]), (5, ["d6e"])]):
        def one(idx=idx, keys=keys):
            f.go("/d6")
            new = p.get_by_role("button", name="محادثة جديدة")
            if new.count() and new.first.is_visible():
                f.click(new); p.wait_for_timeout(800)
            f.click(p.locator("[data-test=suggested]").nth(idx))
            if len(keys) > 1:
                f.say(keys[0])
            f.fast(lambda: p.locator("[data-test=answer]").first.wait_for(timeout=T), "المساعد يعمل")
            if idx == 5:
                safe(f, "d6 code ran", lambda: p.locator("[data-test=code-ran]").first.wait_for(timeout=T))
            p.wait_for_timeout(1500)
            f.show(p.locator("[data-test=answer]").first, block="start", wait=1000)
            f.say(keys[-1]); f.off()
        safe(f, f"d6 #{idx}", one)


def d7(f: Film):
    p = f.p
    f.card("7", "معالجة الشكاوى المخصّصة", "Complaints Personalisation")
    f.go("/d7")
    f.click(p.get_by_role("button", name="فرز الكل"))
    f.say("d7a")
    f.fast(lambda: p.wait_for_function("() => !document.body.innerText.includes('Classifying, routing')", timeout=T), "فرز الشكاوى وصياغة الردود")
    p.wait_for_timeout(1000)
    f.say("d7b"); f.off()
    item = p.locator("[data-test=queue-item]").filter(has_text="S4").first
    f.click(item)
    p.locator("[data-test=draft]").wait_for(timeout=T); p.wait_for_timeout(800)
    f.show(p.locator("[data-test=draft]"), block="center")
    f.say("d7c")

    def approve():
        f.click(p.get_by_role("button", name="اعتماد وإرسال"))
        p.wait_for_timeout(1500); f.say("d7d"); f.off()
    safe(f, "d7 approve", approve)
    f.top()

    def trends():
        f.click(p.get_by_role("button", name="الاتجاهات"))
        f.fast(lambda: p.get_by_text("themes found").first.wait_for(timeout=T), "تجميع المحاور")
        p.wait_for_timeout(1000); f.say("d7e"); f.off()
    safe(f, "d7 trends", trends)

    def acc():
        f.top(); f.click(p.get_by_role("button", name="الدقة"))
        f.fast(lambda: p.get_by_text("Topic accuracy").first.wait_for(timeout=T), "حساب الدقة")
        p.wait_for_timeout(1000); f.say("d7f"); f.off()
    safe(f, "d7 accuracy", acc)


def outro(f: Film):
    f.card("", "سبع حالات استخدام · جهاز واحد · دون إنترنت", "Seven use cases · one machine · fully offline", "مصرف المغرب × Dell Pro Max with GB10")
    f.say("outro", extra=1.5); f.off(1200)


SCENES = [("intro", intro), ("d1", d1), ("d2", d2), ("d3", d3), ("d4", d4), ("d5", d5), ("d6", d6), ("d7", d7), ("outro", outro)]


def main():
    ff = None
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=False, args=["--window-position=0,0", "--window-size=1536,950",
                                                    "--force-device-scale-factor=1.25", "--hide-scrollbars", "--disable-infobars",
                                                    "--autoplay-policy=no-user-gesture-required", "--lang=ar"])
        ctx = b.new_context(no_viewport=True, locale="ar-MA")
        ctx.add_init_script(OVERLAY)
        page = ctx.new_page()
        page.goto(f"{B}/?lang=ar", wait_until="networkidle"); page.wait_for_timeout(1500)
        if not REH:
            ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-video_size", "1920x1080", "-framerate", "30",
                                   "-draw_mouse", "0", "-i", os.environ.get("DISPLAY", ":99") + "+0,108", "-c:v", "libx264", "-preset", "ultrafast",
                                   "-crf", "14", "-pix_fmt", "yuv420p", str(OUT / "raw.mkv")], stdin=subprocess.PIPE)
            time.sleep(1.0)
        f = Film(page, time.time())
        for name, fn in SCENES:
            if ONLY and name not in ONLY:
                continue
            f.ev.append({"scene": name, "t": f.now()})
            f.log("== scene", name)
            safe(f, name, lambda: fn(f))
        f.ev.append({"end": f.now()})
        if ff:
            ff.stdin.write(b"q"); ff.stdin.flush(); ff.wait(timeout=60)
        json.dump(f.ev, open(OUT / ("events_rehearse.json" if REH else "events.json"), "w"), ensure_ascii=False, indent=1)
        b.close()


if __name__ == "__main__":
    main()
