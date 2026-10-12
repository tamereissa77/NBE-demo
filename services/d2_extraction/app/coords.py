"""
coords.py — Bounding Box Coordinate Correction Utilities
=========================================================
Pure-Python, zero heavy dependencies.
Extracted from extractor.py so unit tests can import without torch/transformers.

Chandra OCR-2 coordinate system note:
    The model outputs bboxes in a 0–1000 INTEGER coordinate space.
    Historical bug (fix_json_coords.py): bboxes were treated as pixel coords
    and divided by scale, which compounded the error.
    Correct formula: pixel = (val / 1000.0) * original_dimension
"""

from __future__ import annotations

from PIL import Image

from app.schemas import BBox


def correct_bbox(
    raw_bbox: list | None,
    orig_w: int,
    orig_h: int,
    inf_w: int,
    inf_h: int,
    scale: float,
) -> BBox | None:
    """
    Convert Chandra OCR-2 bbox output → original-image pixel coordinates.

    Handles two possible model output formats:
      A) 0–1000 integer space  (Chandra OCR-2 default)
      B) Normalized 0.0–1.0 floats (alternative format)

    Args:
        raw_bbox:  [x1, y1, x2, y2] from the model
        orig_w:    Width of the original (full-res) image in pixels
        orig_h:    Height of the original (full-res) image in pixels
        inf_w:     Width of the image that was fed to the model
        inf_h:     Height of the image that was fed to the model
        scale:     Downscale factor applied before inference (< 1.0 = shrunk)

    Returns:
        BBox in original pixel coordinates, or None if bbox is invalid.
    """
    if raw_bbox is None or len(raw_bbox) != 4:
        return None

    x1, y1, x2, y2 = raw_bbox

    # Case A: normalized floats [0.0–1.0]
    if all(isinstance(v, float) and 0.0 <= v <= 1.0 for v in [x1, y1, x2, y2]):
        # Convert to inference-res pixels, then scale back to original
        x1 = x1 * inf_w
        y1 = y1 * inf_h
        x2 = x2 * inf_w
        y2 = y2 * inf_h
        if scale < 1.0:
            inv = 1.0 / scale
            x1, y1, x2, y2 = x1 * inv, y1 * inv, x2 * inv, y2 * inv

    # Case B: 0–1000 integer space (Chandra OCR-2 default)
    else:
        x1 = (x1 / 1000.0) * orig_w
        y1 = (y1 / 1000.0) * orig_h
        x2 = (x2 / 1000.0) * orig_w
        y2 = (y2 / 1000.0) * orig_h

    if x2 <= x1 or y2 <= y1:
        return None

    return BBox(x1=round(x1), y1=round(y1), x2=round(x2), y2=round(y2))


def resize_for_inference(
    image: "Image.Image",
    max_dim: int,
) -> tuple["Image.Image", float]:
    """
    Downscale image so its longest side ≤ max_dim, preserving aspect ratio.

    Args:
        image:    PIL Image to resize.
        max_dim:  Maximum pixel dimension for either side.

    Returns:
        (resized_image, scale_factor)
        scale_factor == 1.0 means no resize was needed.
    """
    w, h = image.size
    if max(w, h) <= max_dim:
        return image, 1.0
    scale = max_dim / max(w, h)
    new_w, new_h = int(w * scale), int(h * scale)
    return image.resize((new_w, new_h), Image.LANCZOS), scale
