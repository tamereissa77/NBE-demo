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


# ---- checks for photographed documents (uploads). Measured with planted edits on real photos: docs/workstation.md.
# Both compare a region with the camera noise around it, so neither can say anything about a page that has
# no noise at all (a file made on a computer, a heavily compressed web image): they report "checkable": False.

def _gray(path: str, long_side: int) -> tuple[np.ndarray, float]:
    """Greyscale pixels, shrunk so the longer side is at most `long_side`; the factor maps boxes back."""
    g = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if g is None:                        # a format OpenCV does not read: go through Pillow
        g = np.asarray(Image.open(path).convert("L"))
    f = min(1.0, long_side / max(g.shape))
    if f < 1.0:
        g = cv2.resize(g, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    return g, f


def _paper_noise(g: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """(|high-pass residual|, ink mask, paper mask, typical residual on paper). Paper is everything away from
    strokes and the ringing around them, so print does not count as noise."""
    gf = g.astype(np.float32)
    resid = np.abs(gf - cv2.medianBlur(g, 5).astype(np.float32))
    ink = (gf < cv2.blur(gf, (31, 31)) - 22).astype(np.uint8)
    paper = (cv2.dilate(ink, np.ones((7, 7), np.uint8)) == 0).astype(np.float32)
    level = float(np.median(resid[paper > 0])) if paper.any() else 0.0
    return resid, ink, paper, level


def pasted_patch(path: str, drop: float = 0.3, min_page_noise: float = 0.5) -> dict:
    """A value typed over a photo sits on a patch that has no camera noise, while the paper right around it
    does. This looks for a filled box with writing in it whose background is flat although its surroundings
    are not. Compared locally, not against the whole page, so a blown-out highlight raises nothing."""
    g, f = _gray(path, 1800)
    h, w = g.shape
    resid, ink, paper, level = _paper_noise(g)
    if level < min_page_noise:
        return {"checkable": False, "page_noise": round(level, 2), "regions": [], "suspicious": False}

    def local(k):
        return cv2.blur(resid * paper, (k, k)) / np.maximum(cv2.blur(paper, (k, k)), 1e-3)

    wide = max(41, (min(h, w) // 8) | 1)
    here, around = local(9), local(wide)
    flat = (cv2.blur(paper, (9, 9)) > 0.3) & (here < drop * around) & (around >= min_page_noise) & (cv2.blur(g.astype(np.float32), (9, 9)) < 252)
    flat = cv2.morphologyEx(flat.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))   # across the strokes inside the box
    flat = cv2.morphologyEx(flat, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(flat, connectivity=8)
    regions = []
    for x, y, bw, bh, area in (tuple(int(v) for v in stats[i]) for i in range(1, count)):
        if area < max(300, 0.0004 * h * w) or area < 0.6 * bw * bh or min(bw, bh) < 10:   # too small, or not a filled box
            continue
        if x <= 1 or y <= 1 or x + bw >= w - 1 or y + bh >= h - 1:                         # the surface around the page
            continue
        if ink[y:y + bh, x:x + bw].mean() < 0.02:                                           # nothing written on it: nothing changed
            continue
        regions.append({"bbox": [int(x / f), int(y / f), int((x + bw) / f), int((y + bh) / f)], "area": area})
    regions.sort(key=lambda r: -r["area"])
    return {"checkable": True, "page_noise": round(level, 2), "regions": regions[:3], "suspicious": bool(regions)}


_DCT = [(0, 0), (0, 1), (1, 0), (1, 1), (0, 2), (2, 0)]        # the low frequencies of an 8x8 block


def copy_move(path: str, min_blocks: int = 150, min_shift: int = 24, min_page_noise: float = 0.5) -> dict:
    """A region copied to another place in the same photo (a cloned stamp, signature or line of text).
    Two photographed prints of the same word are never the same pixels; a pasted copy is. Every 8x8 block is
    reduced to its coarse low frequencies, identical blocks are paired, and a copy shows as many pairs that
    all sit at exactly one shift."""
    g, f = _gray(path, 1200)
    _, _, _, level = _paper_noise(g)
    out = {"checkable": level >= min_page_noise, "blocks": 0, "boxes": None, "duplicate": False}
    if not out["checkable"]:
        return out
    gf = g.astype(np.float32)
    h, w = g.shape[0] - 8, g.shape[1] - 8
    i = np.arange(8, dtype=np.float32)
    feats = []
    for u, v in _DCT:
        kernel = np.outer(np.cos((2 * i + 1) * u * np.pi / 16), np.cos((2 * i + 1) * v * np.pi / 16)) / 8
        coarse = np.round(cv2.filter2D(gf, cv2.CV_32F, kernel, anchor=(0, 0), borderType=cv2.BORDER_REPLICATE)[:h, :w] / (16 if (u, v) != (0, 0) else 4))
        feats.append(coarse.astype(np.int64))
    mean = cv2.blur(gf, (8, 8), anchor=(0, 0))[:h, :w]
    textured = (cv2.blur(gf * gf, (8, 8), anchor=(0, 0))[:h, :w] - mean * mean) > 15 ** 2   # blank paper matches everywhere
    ys, xs = np.nonzero(textured)
    if len(ys) < 2 * min_blocks:
        return out
    key = np.zeros(len(ys), np.int64)
    for k, feat in enumerate(feats):
        key = key * 1009 + (feat[ys, xs] + 4096)
    order = np.argsort(key, kind="stable")
    key, ys, xs = key[order], ys[order], xs[order]
    same = key[1:] == key[:-1]
    # a block that occurs many times is a pattern (rules, hatching, guilloche), not a copy: keep pairs only
    lone = same & ~np.r_[False, same[:-1]] & ~np.r_[same[1:], False]
    a = np.flatnonzero(lone)
    dy, dx = ys[a + 1] - ys[a], xs[a + 1] - xs[a]
    flip = (dy < 0) | ((dy == 0) & (dx < 0))
    dy, dx = np.where(flip, -dy, dy), np.where(flip, -dx, dx)
    sy, sx = np.where(flip, ys[a + 1], ys[a]), np.where(flip, xs[a + 1], xs[a])
    far = np.hypot(dy, dx) >= min_shift
    if int(far.sum()) < min_blocks:
        return out
    shifts, counts = np.unique(np.stack([dy[far], dx[far]], axis=1), axis=0, return_counts=True)
    top = int(counts.argmax())
    out["blocks"] = int(counts[top])
    pick = far & (dy == shifts[top][0]) & (dx == shifts[top][1])
    y0, y1, x0, x1 = int(sy[pick].min()), int(sy[pick].max()) + 8, int(sx[pick].min()), int(sx[pick].max()) + 8
    ty, tx = int(shifts[top][0]), int(shifts[top][1])
    # The same words printed twice (the rows of a statement) match block for block as well. What only a copy
    # carries over is the camera noise: in a copy the grain of the paper matches too, in repeated print it does not.
    grain = gf - cv2.medianBlur(g, 5).astype(np.float32)
    _, _, paper, _ = _paper_noise(g)
    a, b = grain[y0:y1, x0:x1], grain[y0 + ty:y1 + ty, x0 + tx:x1 + tx]
    quiet = (paper[y0:y1, x0:x1] > 0) & (paper[y0 + ty:y1 + ty, x0 + tx:x1 + tx] > 0) if a.shape == b.shape else None
    if quiet is None or quiet.sum() < 150:
        return out
    out["grain_match"] = round(float((a * b)[quiet].sum() / (np.sqrt((a * a)[quiet].sum() * (b * b)[quiet].sum()) + 1e-6)), 2)
    if out["blocks"] >= min_blocks and min(y1 - y0, x1 - x0) >= 16 and out["grain_match"] >= 0.3:
        out["boxes"] = [[int(x0 / f), int(y0 / f), int(x1 / f), int(y1 / f)],
                        [int((x0 + tx) / f), int((y0 + ty) / f), int((x1 + tx) / f), int((y1 + ty) / f)]]
        out["duplicate"] = True
    return out


def recompressed(path: str, k: float = 4.0, min_blocks: int = 4) -> dict:
    """An edited JPEG has been saved twice. The original pixels went through the first save (the camera's, or
    the app that shared the photo) and then the save after editing; what was typed or pasted in between went
    through the last one only. Saving the picture again at the first save's quality changes the original
    pixels less than at neighbouring qualities (a "ghost" of that save), and changes the new pixels as much
    as at any other. This looks for a block of content without the ghost the rest of the page has.
    It can say nothing when there is no ghost to compare with: a picture saved once, or re-saved at a lower
    quality than before."""
    out = {"checkable": False, "first_quality": None, "regions": [], "suspicious": False}
    img = Image.open(path)
    if img.format != "JPEG":
        return out
    y = np.asarray(img.convert("L"), dtype=np.float32)
    b = 16
    h, w = (y.shape[0] // b) * b, (y.shape[1] // b) * b
    if h < 8 * b or w < 8 * b:
        return out
    y = y[:h, :w]
    src = Image.fromarray(y.astype(np.uint8))
    qualities = list(range(45, 100, 5))
    diffs = []
    for q in qualities:
        buf = io.BytesIO()
        src.save(buf, "JPEG", quality=q)
        d = (np.asarray(Image.open(buf), dtype=np.float32) - y) ** 2
        diffs.append(d.reshape(h // b, b, w // b, b).mean(axis=(1, 3)))
    d = np.stack(diffs)                                          # quality x blocks
    busy = y.reshape(h // b, b, w // b, b).std(axis=(1, 3)) > 12  # blank paper is unchanged at every quality
    # A ruled line, a table border or the edge of a colour band changes along one direction only, and such
    # blocks keep little of any save's trace: on generated pages they were the false alarms. Content (print,
    # a stamp, a photo) changes in both directions.
    across = np.pad(np.abs(y[:, 1:] - y[:, :-1]), ((0, 0), (0, 1))).reshape(h // b, b, w // b, b).mean(axis=(1, 3))
    down = np.pad(np.abs(y[1:] - y[:-1]), ((0, 1), (0, 0))).reshape(h // b, b, w // b, b).mean(axis=(1, 3))
    busy &= np.minimum(across, down) > 0.35 * np.maximum(across, down)
    if busy.sum() < 40:
        return out
    n = d / (d.mean(axis=0, keepdims=True) + 1e-3)
    curve = np.median(n[:, busy], axis=1)
    last = int(curve.argmin())                                   # the quality it was last saved at leaves it nearly unchanged
    dips = [i for i in range(1, last - 1) if curve[i] < curve[i - 1] and curve[i] < curve[i + 1]]
    if not dips:
        return out
    first = min(dips, key=lambda i: curve[i] - (curve[i - 1] + curve[i + 1]) / 2)
    depth = (n[first - 1] + n[first + 1]) / 2 - n[first]         # how much of a ghost each block shows
    typical = float(np.median(depth[busy]))
    spread = 1.4826 * float(np.median(np.abs(depth[busy] - typical))) + 1e-3
    if typical < 0.02:                                           # a dip in the curve, but no ghost worth the name
        return out
    out.update(checkable=True, first_quality=qualities[first])
    odd = (busy & (depth < typical - k * spread) & (depth < 0.25 * typical)).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(odd, connectivity=8)
    regions = [{"bbox": [int(x * b), int(yy * b), int((x + bw) * b), int((yy + bh) * b)], "blocks": int(area)}
               for x, yy, bw, bh, area in (stats[i] for i in range(1, count)) if area >= min_blocks]
    regions.sort(key=lambda r: -r["blocks"])
    out.update(regions=regions[:3], suspicious=bool(regions))
    return out


def resampled(path: str, win: int = 96, k: float = 6.0) -> dict:
    """A block pasted in from another picture has usually been resized to fit, and resizing leaves a regular
    rhythm in the pixels that an untouched area does not have. Every window is scored for the strongest such
    rhythm (leaving out the 8-pixel one every JPEG has); a cluster of windows far above the page's own level
    is reported. A whole picture that was resized (most shared photos) has the rhythm everywhere and raises nothing."""
    g, f = _gray(path, 1600)
    gf = g.astype(np.float32)
    lap = np.abs(gf[:, 2:] - 2 * gf[:, 1:-1] + gf[:, :-2])        # second difference along a row
    rows, cols = lap.shape[0] // win, lap.shape[1] // win
    out = {"regions": [], "suspicious": False}
    if rows < 3 or cols < 3:
        return out
    score = np.zeros((rows, cols), np.float32)
    freqs = np.fft.rfftfreq(win)
    keep = (freqs > 0.06) & (np.abs(freqs * 8 - np.round(freqs * 8)) > 0.08)   # not the slow drift, not JPEG's 8-pixel grid
    for r in range(rows):
        for c in range(cols):
            block = lap[r * win:(r + 1) * win, c * win:(c + 1) * win]
            if block.mean() < 1.0:                                # nothing in it
                continue
            spec = np.abs(np.fft.rfft(block.mean(axis=0) - block.mean()))[keep]
            score[r, c] = spec.max() / (np.median(spec) + 1e-6)
    seen = score[score > 0]
    if len(seen) < 6:
        return out
    typical = float(np.median(seen))
    spread = 1.4826 * float(np.median(np.abs(seen - typical))) + 1e-3
    odd = (score > typical + k * spread).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(odd, connectivity=8)
    regions = [{"bbox": [int(x * win / f), int(y * win / f), int((x + bw) * win / f), int((y + bh) * win / f)], "windows": int(area)}
               for x, y, bw, bh, area in (stats[i] for i in range(1, count)) if area >= 2]
    out.update(regions=regions[:3], suspicious=bool(regions))
    return out
