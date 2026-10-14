#!/usr/bin/env python3
"""Make one customer the active one:   scripts/apply_customer.py <name>   (make customer NAME=<name>)

Reads customers/<name>/customer.json and its logo, then writes everything the build and the services read:
  brand/                 logo.png, mark.png, logo-full.png, theme.css (colours from the logo unless overridden),
                         brand.json (names + the country's portal locale)    -> the portal, at build time
  data/customer.json     names and the bank's own facts                      -> the services, at /data/customer.json
  .env                   BRAND, BANK_SHORT, BANK_NAME_EN/AR, COUNTRY, TZ,    -> every container
                         BANNER_PALETTE (the colours in words, for D3's image model)
  data/seed-active/      the country's corpus (data/seed/<CC>) with the bank's name swapped in -> /data/seed

The portal must be rebuilt and the data reloaded afterwards; `make customer` does both. Only Pillow is needed.
   --colors-only   print the colours it would pick from the logo, change nothing
   --list          the customer profiles, and which one is active
   --seed-only     only render data/seed-active again for the active customer (after `make data` or `make author`)
"""
import colorsys
import json
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
CUSTOMERS, BRAND_DIR, SEED, ACTIVE = ROOT / "customers", ROOT / "brand", ROOT / "data" / "seed", ROOT / "data" / "seed-active"
COUNTRIES = ROOT / "packages" / "nbe_core" / "nbe_core" / "countries"
FONTS = {"cairo": '"Cairo Variable", "Segoe UI", Tahoma, sans-serif',
         "plex": '"IBM Plex Sans Arabic", "Segoe UI", Tahoma, sans-serif'}
TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".ini", ".txt", ".csv", ".yaml", ".yml"}


def die(msg: str) -> None:
    sys.exit(f"apply_customer: {msg}")


# ------------------------------------------------------------------ colours
def hex_of(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c))) for c in rgb[:3])


def rgb_of(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        die(f"not a colour: #{h} (use #rrggbb)")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def luminance(rgb) -> float:
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def shade(rgb, lightness: float | None = None, factor: float = 1.0):
    """Same hue and saturation; lightness set (0..1) or scaled."""
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb[:3]))
    l = lightness if lightness is not None else max(0.0, min(1.0, l * factor))
    return tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, l, s))


def readable_on_white(rgb, ratio: float = 4.5):
    """Darken until text in this colour reads on white (WCAG AA): logos are often lighter than body text needs."""
    while contrast(rgb, (255, 255, 255)) < ratio:
        rgb = shade(rgb, factor=0.92)
    return rgb


def logo_colors(path: Path) -> list[tuple[tuple[int, int, int], float]]:
    """The logo's distinct colours, most used first, as (rgb, share). White, near-black, grey and transparent
    pixels are left out: they are the background and the lettering, not the brand. Pixels are grouped by hue and
    lightness, and each group is shown by its most frequent exact colour, so the anti-aliased edges of a flat
    logo do not muddy it."""
    img = Image.open(path).convert("RGBA")
    img.thumbnail((480, 480))
    groups: dict[tuple[int, int], Counter] = defaultdict(Counter)
    total = 0
    for r, g, b, a in img.getdata():
        if a <= 128:
            continue
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        if 0.12 < l < 0.93 and s > 0.25:
            groups[(int(h * 24) % 24, min(2, int(l * 3)))][(r, g, b)] += 1
            total += 1
    if total < 30:                                      # a black, grey or white logo: no brand colour in it
        return []
    out: list[list] = []
    for counts in sorted(groups.values(), key=lambda c: -sum(c.values())):
        rgb, n = counts.most_common(1)[0][0], sum(counts.values())
        same = next((o for o in out if _hue_gap(rgb, o[0]) < 0.04 and abs(luminance(rgb) - luminance(o[0])) < 0.15), None)
        if same:
            same[1] += n
        elif n / total >= 0.01:
            out.append([rgb, n])
    return [(rgb, n / total) for rgb, n in sorted(out, key=lambda o: -o[1])]


def _hue_gap(a, b) -> float:
    ha = colorsys.rgb_to_hls(*(c / 255 for c in a))[0]
    hb = colorsys.rgb_to_hls(*(c / 255 for c in b))[0]
    d = abs(ha - hb)
    return min(d, 1 - d)


def pick_colors(logo: Path, override: dict) -> dict:
    found = logo_colors(logo)
    brand = rgb_of(override["brand"]) if override.get("brand") else (found[0][0] if found else (0x1f, 0x2a, 0x44))
    if override.get("accent"):
        accent = rgb_of(override["accent"])
    else:
        others = [c for c, share in found[1:] if _hue_gap(c, brand) > 0.08 and share > 0.03]
        accent = others[0] if others else _default_accent(brand)
    brand = readable_on_white(brand)
    tokens = {
        "brand": brand,
        "brand-dark": shade(brand, factor=0.72),
        "accent": accent,
        "accent-light": shade(accent, lightness=min(0.75, colorsys.rgb_to_hls(*(c / 255 for c in accent))[1] + 0.15)),
        "accent-deep": shade(accent, factor=0.8),
    }
    tokens["on-accent"] = (0x14, 0x14, 0x14) if contrast(accent, (0x14, 0x14, 0x14)) >= contrast(accent, (255, 255, 255)) else (255, 255, 255)
    tokens["ink"] = shade(brand, lightness=0.1) if colorsys.rgb_to_hls(*(c / 255 for c in brand))[2] > 0.2 else (0x14, 0x14, 0x14)
    # "Flagged for review" must stay amber-like and "ok" green-like, whatever the brand is
    tokens["status-review"] = accent if 0.06 < colorsys.rgb_to_hls(*(c / 255 for c in accent))[0] < 0.15 else (0xf2, 0xa9, 0x00)
    tokens["status-ok"] = brand if 0.22 < colorsys.rgb_to_hls(*(c / 255 for c in brand))[0] < 0.5 else (0x2e, 0x7d, 0x32)
    for k, v in override.items():                      # any other token can be set by hand too
        if k not in ("brand", "accent"):
            tokens[k] = rgb_of(v)
    return {k: hex_of(v) for k, v in tokens.items()}


HUES = [(0.03, "red"), (0.07, "orange-red"), (0.11, "orange"), (0.15, "golden"), (0.19, "yellow"), (0.25, "lime green"),
        (0.45, "green"), (0.5, "teal"), (0.54, "turquoise"), (0.6, "sky blue"), (0.7, "blue"), (0.76, "indigo"),
        (0.83, "purple"), (0.92, "magenta"), (0.97, "pink"), (1.01, "red")]


def color_word(hex_color: str) -> str:
    """#00798c -> "deep teal": how the image model is told the brand colours (D3 banners)."""
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb_of(hex_color)))
    if s < 0.15:
        return "charcoal" if l < 0.35 else "silver grey" if l < 0.8 else "white"
    name = next(n for limit, n in HUES if h < limit)
    if name == "orange" and l < 0.35:
        name = "brown"
    tone = "deep " if l < 0.3 else "light " if l > 0.7 else "warm " if name in ("orange", "golden") else ""
    return tone + name


def _default_accent(brand):
    """No second colour in the logo: a warm gold beside a cool brand, a deep teal beside a warm one."""
    h = colorsys.rgb_to_hls(*(c / 255 for c in brand))[0]
    return (0xf2, 0xa9, 0x00) if 0.4 < h < 0.95 else (0x00, 0x7c, 0x89)


def theme_css(c: dict, font: str, name: str, source: str) -> str:
    return f"""/*
 * Brand pack: {name}. Written by scripts/apply_customer.py from customers/{source}: do not edit here.
 * Colours: {', '.join(f'{k} {v}' for k, v in c.items() if k in ('brand', 'accent'))} (from the logo unless set in customer.json "colors").
 */
:root {{
  --brand: {c['brand']};            /* primary: buttons, headings, links */
  --brand-dark: {c['brand-dark']};       /* footer, hover */
  --accent: {c['accent']};           /* chips, highlights, active states */
  --accent-light: {c['accent-light']};     /* footer accent text */
  --accent-deep: {c['accent-deep']};
  --accent-gradient: linear-gradient(90deg, {c['accent-light']} 0%, {c['accent']} 55%, {c['accent-deep']} 100%);
  --on-accent: {c['on-accent']};        /* text on accent fills */

  --canvas: {c.get('canvas', '#f8f8f8')};           /* page background */
  --ink: {c['ink']};              /* strong text */
  --ink-soft: {c.get('ink-soft', '#4a4a4a')};         /* body text */
  --line: {c.get('line', '#d6d6d6')};             /* borders */

  --status-review: {c['status-review']};    /* "flagged for review" */
  --status-stop: {c.get('status-stop', '#c62828')};      /* guardrail STOP */
  --status-ok: {c['status-ok']};

  --font-ui: {FONTS[font]};
}}
"""


# ------------------------------------------------------------------ logo files
def trimmed(img: Image.Image) -> Image.Image:
    """The logo without its empty (transparent or white) margins."""
    rgba = img.convert("RGBA")
    alpha_box = rgba.getchannel("A").point(lambda a: 255 if a > 16 else 0).getbbox()
    white_box = ImageOps.invert(rgba.convert("RGB")).point(lambda v: 255 if v > 18 else 0).getbbox()
    boxes = [b for b in (alpha_box, white_box) if b]
    if not boxes:
        return rgba
    box = (max(b[0] for b in boxes), max(b[1] for b in boxes), min(b[2] for b in boxes), min(b[3] for b in boxes))
    return rgba.crop(box) if box[2] > box[0] and box[3] > box[1] else rgba


def square(img: Image.Image, size: int = 256) -> Image.Image:
    img = img.copy()
    img.thumbnail((int(size * 0.9), int(size * 0.9)), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    out.paste(img, ((size - img.width) // 2, (size - img.height) // 2), img)
    return out


def write_logos(logo: Path, folder: Path) -> None:
    """brand/logo.png (header), logo-full.png and mark.png (square: customers/<name>/mark.png, or the logo)."""
    img = trimmed(Image.open(logo))
    full = img.copy()
    full.thumbnail((1200, 400), Image.LANCZOS)
    full.save(BRAND_DIR / "logo-full.png")
    head = img.copy()
    head.thumbnail((600, 160), Image.LANCZOS)          # the header shows it 40-48 px high
    head.save(BRAND_DIR / "logo.png")
    mark = folder / "mark.png"                           # the round avatar (D4) and the demo page emblem
    (square(trimmed(Image.open(mark))) if mark.exists() else square(img)).save(BRAND_DIR / "mark.png")


# ------------------------------------------------------------------ the country
def country_portal(code: str) -> dict:
    """The country's portal locale (PORTAL in nbe_core/countries/<cc>.py), read without importing nbe_core."""
    path = COUNTRIES / f"{code.lower()}.py"
    if not path.exists():
        die(f"no country pack for {code}: expected {path.relative_to(ROOT)} (available: "
            + ", ".join(p.stem.upper() for p in sorted(COUNTRIES.glob('[a-z][a-z].py'))) + ")")
    scope: dict = {}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), scope)
    for key in ("PORTAL", "TZ"):
        if key not in scope:
            die(f"{path.relative_to(ROOT)} has no {key}")
    return {"portal": scope["PORTAL"], "tz": scope["TZ"]}


# ------------------------------------------------------------------ the corpus
def render_seed(code: str, names: dict) -> str:
    """data/seed/<CC> -> data/seed-active with the bank's name swapped in (the corpus was authored for the bank in
    data/seed/<CC>/bank.json). Binary files are hard-linked, so a re-render is quick and takes no space.
    The folder itself is emptied, never replaced: running containers have it bind-mounted as /data/seed, and a new
    folder would leave them looking at the deleted one."""
    src = SEED / code
    ACTIVE.mkdir(parents=True, exist_ok=True)
    for child in ACTIVE.iterdir():
        shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
    if not src.is_dir():
        return "missing"
    complete = has_corpus(code)
    authored = json.loads((src / "bank.json").read_text(encoding="utf-8")) if (src / "bank.json").exists() else {}
    swaps = {}
    for key, word in (("ar", False), ("en", False), ("short", True)):
        old, new = authored.get(key), names.get(key)
        if old and new and old != new:
            swaps[old] = (new, word)
    if authored.get("ar") and names.get("ar") and authored["ar"] != names["ar"]:
        li = lambda n: "ل" + n[1:] if n.startswith("ال") else "ل" + n          # للبنك الأهلي / لبنك الرياض
        swaps[li(authored["ar"])] = (li(names["ar"]), False)
    pattern = None
    if swaps:
        alts = sorted(swaps, key=len, reverse=True)
        pattern = re.compile("|".join(rf"(?<![A-Za-z]){re.escape(a)}(?![A-Za-z])" if swaps[a][1] else re.escape(a) for a in alts))
    changed = 0
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        dst = ACTIVE / rel
        if path.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if pattern and path.suffix in TEXT_SUFFIXES and path.name != "bank.json":
            text = path.read_text(encoding="utf-8")
            new = pattern.sub(lambda m: swaps[m.group(0)][0], text)
            if new != text:
                changed += 1
                if path.suffix in (".json", ".jsonl"):
                    _check_json(new, rel)
            dst.write_text(new, encoding="utf-8")
        else:
            try:
                os.link(path, dst)
            except OSError:
                shutil.copy2(path, dst)
    os.chmod(ACTIVE, 0o755)
    if not complete:
        return "missing"
    return f"{changed} file(s) renamed from {authored.get('en', '?')}" if changed else "as authored"


def has_corpus(code: str) -> bool:
    """The country's corpus has been authored (make author): until then data/seed/<CC> holds only the hand-made
    files (D4 pronunciation, D7 policy)."""
    return (SEED / code / "d2" / "manifest.json").exists() and (SEED / code / "d5" / "manifest.json").exists()


def _check_json(text: str, rel: Path) -> None:
    try:
        if rel.suffix == ".jsonl":
            for line in text.splitlines():
                line.strip() and json.loads(line)
        else:
            json.loads(text)
    except ValueError as e:
        die(f"renaming the bank broke {rel}: {e}")


# ------------------------------------------------------------------ .env
def set_env(values: dict) -> None:
    env = ROOT / ".env"
    if not env.exists():
        die(".env is missing: run `make .env` first")
    lines = env.read_text(encoding="utf-8").splitlines()
    done = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in values and not line.lstrip().startswith("#"):
            lines[i] = f"{key}={_quote(values[key])}"
            done.add(key)
    missing = [k for k in values if k not in done]
    if missing:
        lines += ["", "# --- active customer (make customer NAME=...): written by scripts/apply_customer.py ---"]
        lines += [f"{k}={_quote(values[k])}" for k in missing]
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _quote(v: str) -> str:
    return f'"{v}"' if re.search(r"\s", v) else v


# ------------------------------------------------------------------ main
def list_customers() -> None:
    active = ROOT / "data" / "customer.json"
    current = json.loads(active.read_text(encoding="utf-8")).get("id") if active.exists() else None
    for f in sorted(CUSTOMERS.glob("*/customer.json")):
        if f.parent.name.startswith("_"):
            continue
        c = json.loads(f.read_text(encoding="utf-8"))
        corpus = "" if has_corpus(c["country"].upper()) else "   (no corpus yet: make author)"
        mark = "*" if c.get("id", f.parent.name) == current else " "
        print(f" {mark} {f.parent.name:<14} {c['country'].upper()}  {c['name']['en']}{corpus}")


def main() -> None:
    if "--list" in sys.argv:
        return list_customers()
    if "--seed-only" in sys.argv:
        active = ROOT / "data" / "customer.json"
        if not active.exists():
            die("no active customer yet: run `make customer NAME=<name>` first")
        c = json.loads(active.read_text(encoding="utf-8"))
        seed = render_seed(c["country"], {"ar": c["name"]["ar"], "en": c["name"]["en"], "short": c["short"]})
        print(f"corpus     data/seed/{c['country']} -> data/seed-active ({seed})")
        sys.exit(3 if seed == "missing" else 0)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        names = sorted(p.name for p in CUSTOMERS.iterdir() if (p / "customer.json").exists())
        die("usage: apply_customer.py <name> [--colors-only]   customers: " + ", ".join(names))
    folder = CUSTOMERS / args[0]
    if not (folder / "customer.json").exists():
        die(f"{folder.relative_to(ROOT)}/customer.json not found (copy customers/_template to start one)")
    cust = json.loads((folder / "customer.json").read_text(encoding="utf-8"))
    for key in ("short", "name", "country"):
        if not cust.get(key):
            die(f"customer.json needs '{key}'")
    code = cust["country"].upper()
    country = country_portal(code)
    logo = folder / cust.get("logo", "logo.png")
    if not logo.exists():
        die(f"{logo.relative_to(ROOT)} is missing: put the customer's logo (PNG, ideally transparent) there")

    colors = pick_colors(logo, cust.get("colors") or {})
    if "--colors-only" in sys.argv:
        found = logo_colors(logo)
        print("in the logo: " + (", ".join(f"{hex_of(c)} ({s:.0%})" for c, s in found) or "no brand colour (black, grey or white)"))
        print("theme:       " + ", ".join(f"{k} {v}" for k, v in colors.items()))
        return

    name, short = cust["name"], cust["short"]
    font = cust.get("font", "cairo")
    if font not in FONTS:
        die(f"font must be one of {', '.join(FONTS)} (the fonts bundled in the portal)")
    li_ar = "ل" + name["ar"][1:] if name["ar"].startswith("ال") else "ل" + name["ar"]

    # brand/
    if BRAND_DIR.exists():
        shutil.rmtree(BRAND_DIR)
    BRAND_DIR.mkdir()
    write_logos(logo, folder)
    (BRAND_DIR / "theme.css").write_text(theme_css(colors, font, name["en"], args[0]), encoding="utf-8")
    brand = {
        "id": cust.get("id", args[0]),
        "short": short,
        "name": name,
        "assistant": cust.get("assistant") or {"en": f"{short} AI Assistant", "ar": f"المساعد الذكي {li_ar}"},
        "appTitle": cust.get("appTitle") or {"en": f"{short} AI Demos", "ar": f"عروض الذكاء الاصطناعي {li_ar}"},
        "agentName": cust.get("agentName") or {"en": f"{short} Virtual Agent", "ar": f"المساعد الافتراضي {li_ar}"},
        "website": cust.get("website", ""),
        **{k: cust[k] for k in ("heroTitle", "heroChips") if k in cust},
        "locale": {"code": code, **country["portal"]},
        "note": f"Written by scripts/apply_customer.py from customers/{args[0]}. Synthetic demo content only.",
    }
    (BRAND_DIR / "brand.json").write_text(json.dumps(brand, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # data/customer.json (read by nbe_core.locale inside the containers)
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "customer.json").write_text(json.dumps(
        {"id": brand["id"], "short": short, "name": name, "country": code, "facts": cust.get("facts", [])},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # .env
    palette = cust.get("bannerPalette") or f"{color_word(colors['brand'])} and {color_word(colors['accent'])} colour palette"
    set_env({"BRAND": brand["id"], "BANK_SHORT": short, "BANK_NAME_EN": name["en"], "BANK_NAME_AR": name["ar"],
             "COUNTRY": code, "TZ": country["tz"], "BANNER_PALETTE": palette})

    # data/seed-active/
    seed = render_seed(code, {"ar": name["ar"], "en": name["en"], "short": short})

    print(f"customer   {name['en']} ({short}), {country['portal']['country']['en']} [{code}]")
    print(f"colours    brand {colors['brand']}, accent {colors['accent']} ({'set in customer.json' if cust.get('colors') else 'from the logo'})")
    print(f"font       {font};  banners: {palette}")
    if seed == "missing":
        print(f"corpus     NONE for {code} yet: author it once with `make author` (about 25 min, needs the LLM running)")
        sys.exit(3)
    print(f"corpus     data/seed/{code} -> data/seed-active ({seed})")


if __name__ == "__main__":
    main()
