"""
cropper.py — Visual Crop Generation
=====================================
For every extracted block with a valid bounding box, crop the corresponding
region from the original page image and save it as a PNG.

These crops are the citation visuals shown in the chatbot UI pop-up.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from app.schemas import Block, PageResult
from app.config import settings

log = logging.getLogger(__name__)


def crop_block(
    page_image: Image.Image,
    block: Block,
    output_path: Path,
    padding: int = settings.crop_padding_px,
) -> bool:
    """
    Crop a single block from the full page image and save it as PNG.

    Args:
        page_image:  PIL Image of the full page (original resolution).
        block:       Block with a valid bbox in original pixel coordinates.
        output_path: Where to save the PNG.
        padding:     Extra pixels added around the bbox (context buffer).

    Returns:
        True if the crop was saved; False if bbox is missing or invalid.
    """
    if block.bbox is None:
        return False

    img_w, img_h = page_image.size
    x1, y1, x2, y2 = block.bbox.x1, block.bbox.y1, block.bbox.x2, block.bbox.y2

    # Sanity check
    if x2 <= x1 or y2 <= y1:
        log.debug(f"Skipping {block.block_id}: degenerate bbox {block.bbox}")
        return False

    # Apply padding clamped to image boundaries
    x1p = max(0, x1 - padding)
    y1p = max(0, y1 - padding)
    x2p = min(img_w, x2 + padding)
    y2p = min(img_h, y2 + padding)

    crop = page_image.crop((x1p, y1p, x2p, y2p))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(str(output_path), format="PNG", optimize=True)
    return True


def generate_crops_for_page(
    page_result: PageResult,
    page_image_path: str,
    output_dir: Path,
) -> PageResult:
    """
    Generate crops for all blocks in a PageResult and update crop_path fields.

    Crops are saved to:
        {output_dir}/crops/{doc_id}/{page_NNN}/{block_id}_{block_type}.png

    The crop_path stored in the block is the RELATIVE path from output_dir:
        crops/{doc_id}/{page_NNN}/{block_id}_{block_type}.png

    This relative path is later used to construct the MinIO URL.

    Args:
        page_result:      PageResult from the extractor (blocks have bbox but no crop_path).
        page_image_path:  Absolute path to the original page PNG.
        output_dir:       Root output directory (shared volume mount).

    Returns:
        Updated PageResult with crop_path fields populated.
    """
    doc_id = page_result.doc_id
    page_num = page_result.page_num
    page_name = f"page_{page_num:03d}"

    crops_dir = output_dir / "crops" / doc_id / page_name
    crops_dir.mkdir(parents=True, exist_ok=True)

    page_image = Image.open(page_image_path).convert("RGB")

    crops_generated = 0
    crops_skipped = 0

    for block in page_result.blocks:
        crop_filename = f"{block.block_id}_{block.block_type.value}.png"
        crop_abs_path = crops_dir / crop_filename
        crop_rel_path = f"crops/{doc_id}/{page_name}/{crop_filename}"

        # Resume: skip if already cropped
        if crop_abs_path.exists():
            block.crop_path = crop_rel_path
            crops_generated += 1
            continue

        success = crop_block(page_image, block, crop_abs_path)
        if success:
            block.crop_path = crop_rel_path
            crops_generated += 1
        else:
            block.crop_path = None
            crops_skipped += 1

    log.info(
        f"  Crops [{doc_id} p{page_num:03d}]: "
        f"{crops_generated} generated, {crops_skipped} skipped (no valid bbox)"
    )
    return page_result


def generate_crops_for_document(
    pages: list[PageResult],
    page_image_dir: str,
    output_dir: Path,
) -> list[PageResult]:
    """
    Generate crops for all pages of a document.

    Args:
        pages:           List of PageResult objects from the extractor.
        page_image_dir:  Directory containing page_001.png … page_NNN.png.
        output_dir:      Root output directory.

    Returns:
        Updated list of PageResult objects with crop_path fields populated.
    """
    updated = []
    for page in pages:
        image_path = (
            Path(page_image_dir) / f"page_{page.page_num:03d}.png"
        )
        if not image_path.exists():
            log.warning(f"Page image not found: {image_path} — skipping crops")
            updated.append(page)
            continue
        updated.append(
            generate_crops_for_page(page, str(image_path), output_dir)
        )
    return updated
