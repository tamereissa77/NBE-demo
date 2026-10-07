"""Image forensics for D1. Each check returns evidence a reviewer can see, never a verdict on its own.

- ELA (error level analysis): re-save the JPEG and look for regions whose compression error differs
  from the rest of the page, the trace a pasted, re-typed value leaves.
- Duplicate stamps: generic copy-move detection fires on repeated letters and the repeating SPECIMEN
  watermark of text documents, so this looks specifically for two near-identical ink stamps.
- Metadata: an editing application in the EXIF Software tag.
"""
import base64
import io

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageFilter

EDITORS = ("photoshop", "gimp", "lens", "editor", "pixlr", "canva", "snapseed", "lightroom")
BLOCK = 16


def _png_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def ela(path: str, quality: int = 90) -> dict:
    orig = Image.open(path).convert("RGB")
    buf = io.BytesIO()
    orig.save(buf, "JPEG", quality=quality)
    diff = ImageChops.difference(orig, Image.open(io.BytesIO(buf.getvalue())).convert("RGB")).convert("L")
    a = np.asarray(diff, dtype=np.float32)
    h, w = (a.shape[0] // BLOCK) * BLOCK, (a.shape[1] // BLOCK) * BLOCK
    blocks = a[:h, :w].reshape(h // BLOCK, BLOCK, w // BLOCK, BLOCK).mean(axis=(1, 3))
    # Only blocks that contain content (ink) are comparable; blank paper has near-zero error anyway
    ink = np.asarray(orig.convert("L"), dtype=np.float32)[:h, :w].reshape(h // BLOCK, BLOCK, w // BLOCK, BLOCK).min(axis=(1, 3)) < 160
    vals = blocks[ink] if ink.any() else blocks.ravel()
    med, mad = float(np.median(vals)), float(np.median(np.abs(vals - np.median(vals)))) + 1e-3
    z = (blocks - med) / (1.4826 * mad)
    hot = (z > 6) & ink
    # Keep only clusters of hot blocks (a pasted value spans several blocks), not isolated specks
    hot_u8 = hot.astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(hot_u8, connectivity=8)
    regions = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area >= 6:
            regions.append({"bbox": [int(x * BLOCK), int(y * BLOCK), int((x + bw) * BLOCK), int((y + bh) * BLOCK)],
                            "blocks": int(area), "peak_z": round(float(z[labels == i].max()), 1)})
    regions.sort(key=lambda r: -r["peak_z"] * r["blocks"])
    heat = Image.fromarray(np.clip(a * 12, 0, 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3))
    heat = Image.merge("RGB", (heat, heat.point(lambda v: v // 3), Image.new("L", heat.size, 0)))
    heat.thumbnail((620, 900))
    score = round(float(max((r["peak_z"] for r in regions), default=0)), 1)
    return {"score": score, "regions": regions[:3], "suspicious": bool(regions), "heatmap_png": _png_b64(heat),
            "image_size": list(orig.size)}


def noise_inconsistency(path: str) -> dict:
    """Scanned pages carry sensor noise everywhere. A value re-typed into a clean patch, or a pasted photo,
    has almost none: find clusters of blocks whose high-pass noise is far below the page's typical level."""
    g = cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2GRAY).astype(np.float32)
    resid = g - cv2.medianBlur(g.astype(np.uint8), 5).astype(np.float32)
    h, w = (g.shape[0] // BLOCK) * BLOCK, (g.shape[1] // BLOCK) * BLOCK
    std = resid[:h, :w].reshape(h // BLOCK, BLOCK, w // BLOCK, BLOCK).std(axis=(1, 3))
    page = float(np.median(std))
    flat = (std < 0.35 * page).astype(np.uint8)
    flat[:2, :] = flat[-2:, :] = 0      # ignore the outer margin
    flat[:, :2] = flat[:, -2:] = 0
    n, labels, stats, _ = cv2.connectedComponentsWithStats(flat, connectivity=8)
    regions = [{"bbox": [int(x * BLOCK), int(y * BLOCK), int((x + bw) * BLOCK), int((y + bh) * BLOCK)], "blocks": int(a)}
               for x, y, bw, bh, a in (stats[i] for i in range(1, n)) if a >= 8]
    regions.sort(key=lambda r: -r["blocks"])
    return {"page_noise": round(page, 2), "regions": regions[:3], "suspicious": bool(regions)}


def duplicate_stamps(path: str) -> dict:
    img = cv2.imread(path)
    b, g, r = [img[:, :, i].astype(np.int16) for i in range(3)]
    mask = ((b - r > 45) & (b - g > 15)).astype(np.uint8) * 255          # blue ink
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    blobs = [stats[i] for i in range(1, n) if stats[i][4] > 2500 and 120 < stats[i][2] < 400 and 120 < stats[i][3] < 400]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    best = 0.0
    pair = None
    for i in range(len(blobs)):
        for j in range(i + 1, len(blobs)):
            x1, y1, w1, h1, _ = blobs[i]
            x2, y2, w2, h2, _ = blobs[j]
            # Compare ink shapes, which survive re-compression of a cloned region; pixel values do not
            a = mask[y1:y1 + h1, x1:x1 + w1].astype(np.float32)
            bb = cv2.resize(mask[y2:y2 + h2, x2:x2 + w2], (w1, h1)).astype(np.float32)
            sim = float(cv2.matchTemplate(a, bb, cv2.TM_CCOEFF_NORMED).max())
            if sim > best:
                best, pair = sim, [[int(x1), int(y1), int(x1 + w1), int(y1 + h1)], [int(x2), int(y2), int(x2 + w2), int(y2 + h2)]]
    return {"stamps_found": len(blobs), "duplicate": best > 0.85, "similarity": round(best, 3), "boxes": pair}


def metadata(path: str) -> dict:
    exif = Image.open(path).getexif()
    software = str(exif.get(0x0131, "") or "")
    return {"software": software or None, "model": exif.get(0x0110), "editor_detected": any(e in software.lower() for e in EDITORS)}


def thumbnail_b64(path: str, width: int = 620) -> str:
    img = Image.open(path).convert("RGB")
    img.thumbnail((width, int(width * 1.5)))
    return _png_b64(img)


def full_png_b64(path: str, max_side: int = 1600) -> str:
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side))
    return _png_b64(img)
