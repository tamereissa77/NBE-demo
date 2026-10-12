"""
extractor.py — Chandra OCR-2 Extraction Engine (Notebook-aligned version)
==========================================================================
Wraps the datalab-to/chandra-ocr-2 model using the official chandra-ocr library.
Aligned with nbe_stage2_ocr_extraction.ipynb logic.
"""

from __future__ import annotations

import gc
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import torch
from PIL import Image
from bs4 import BeautifulSoup
from chandra.model.hf import generate_hf
from chandra.model.schema import BatchInputItem
from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig
from huggingface_hub import login

from app.schemas import Block, BlockType, PageResult
from app.config import settings
from app.coords import correct_bbox, resize_for_inference

log = logging.getLogger(__name__)

# ── Module-level model state ──────────────────────────────────────────────────
_model = None

# Maps data-label values from the model HTML to our schema BlockType values
LABEL_MAP = {
    "page-header": BlockType.HEADER,
    "page-footer": BlockType.FOOTER,
    "text": BlockType.TEXT,
    "table": BlockType.TABLE,
    "figure": BlockType.FIGURE,
    "list": BlockType.LIST,
    "section-header": BlockType.HEADER,
    "caption": BlockType.TEXT,
}


def is_model_loaded() -> bool:
    """Check if the model is currently loaded in memory."""
    return _model is not None


def load_model() -> None:
    """Load Chandra OCR-2 into GPU memory using 4-bit quantization."""
    global _model

    # Offline first: a local copy of the model needs no login. The gated download is the fallback.
    source, token = settings.chandra_model_path, None
    if not Path(source).is_dir():
        source, token = settings.chandra_model_id, settings.hf_token
        log.info("Logging in to HuggingFace...")
        login(token=token, add_to_git_credential=False)

    if settings.load_in_4bit:
        # As nbe-working loaded it; the existing extractions were made this way.
        log.info(f"Loading Chandra OCR-2 (4-bit) from '{source}'...")
        how = {"quantization_config": BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
        )}
    else:
        # LOAD_IN_4BIT=0: no bitsandbytes, for a machine where it does not run. Needs more memory, and the
        # output may differ slightly from the 4-bit extractions.
        log.info(f"Loading Chandra OCR-2 (bfloat16, not quantised) from '{source}'...")
        how = {"torch_dtype": torch.bfloat16}

    _model = AutoModelForImageTextToText.from_pretrained(
        source,
        device_map="auto",
        token=token,
        **how,
    )
    _model.eval()

    # The chandra-ocr library expects the processor to be attached to the model
    _model.processor = AutoProcessor.from_pretrained(
        source,
        token=token,
    )
    _model.processor.tokenizer.padding_side = "left"

    log.info("Model loaded successfully ✓")


def parse_blocks_from_html(
    raw_html: str,
    doc_id: str,
    page_num: int,
    orig_w: int,
    orig_h: int,
    inf_w: int,
    inf_h: int,
    scale: float,
    language: str,
) -> list[Block]:
    """Parse result.raw (HTML string) into our Block schema."""
    soup = BeautifulSoup(raw_html, "html.parser")
    blocks = []

    # Find all divs with data-bbox (this is what Chandra emits)
    for idx, div in enumerate(soup.find_all("div", attrs={"data-bbox": True})):
        block_id = f"{doc_id}_p{page_num:03d}_b{idx:02d}"

        # --- Block type ---
        raw_label = div.get("data-label", "text").lower().strip()
        block_type = LABEL_MAP.get(raw_label, BlockType.TEXT)

        # --- Bounding box ---
        raw_bbox_str = div.get("data-bbox", "").strip()
        raw_bbox = None
        if raw_bbox_str:
            try:
                parts = list(map(float, raw_bbox_str.split()))
                if len(parts) == 4:
                    raw_bbox = parts
            except (ValueError, TypeError):
                raw_bbox = None

        # Correct bbox from inference scale to original pixels
        bbox = correct_bbox(raw_bbox, orig_w, orig_h, inf_w, inf_h, scale)

        # --- Text content ---
        text = div.get_text(separator=" ", strip=True)

        # --- Table data ---
        table_data = None
        if block_type == BlockType.TABLE:
            # For tables, we keep the inner HTML structure
            table_data = div.decode_contents().strip()

        blocks.append(
            Block(
                block_id=block_id,
                block_type=block_type,
                text=text or "",
                bbox=bbox,
                confidence=None,
                language=language,
                table_data=table_data,
                crop_path=None,
            )
        )

    return blocks


def extract_page(
    doc_id: str,
    doc_name: str,
    doc_type: str,
    page_num: int,
    image_path: str,
    language: str = "ara",
) -> PageResult:
    """Run extraction on a single page using generate_hf."""
    if _model is None:
        raise RuntimeError("Model not loaded. Call load_model() first.")

    original_image = Image.open(image_path).convert("RGB")
    orig_w, orig_h = original_image.size

    inference_image, scale = resize_for_inference(
        original_image, settings.max_inference_dim
    )
    inf_w, inf_h = inference_image.size

    log.info(
        f"  [{doc_id} p{page_num:03d}] "
        f"orig={orig_w}×{orig_h} → inf={inf_w}×{inf_h} scale={scale:.3f}"
    )

    # Use BatchInputItem as in the notebook
    batch = [BatchInputItem(image=inference_image, prompt_type="ocr_layout")]

    with torch.inference_mode():
        results = generate_hf(batch, _model)
        result = results[0]

    if result.error:
        raise RuntimeError(f"Chandra OCR error: {result.error}")

    # Parse the HTML output
    blocks = parse_blocks_from_html(
        raw_html=result.raw,
        doc_id=doc_id,
        page_num=page_num,
        orig_w=orig_w,
        orig_h=orig_h,
        inf_w=inf_w,
        inf_h=inf_h,
        scale=scale,
        language=language,
    )

    # Cleanup GPU memory
    del inference_image, original_image, results, result
    torch.cuda.empty_cache()
    gc.collect()

    return PageResult(
        doc_id=doc_id,
        doc_name=doc_name,
        doc_type=doc_type,
        page_num=page_num,
        original_size=(orig_w, orig_h),
        inference_size=(inf_w, inf_h),
        page_image_path=image_path,
        extraction_timestamp=datetime.now(timezone.utc).isoformat(),
        blocks=blocks,
    )


def extract_document(
    doc_id: str,
    doc_name: str,
    doc_type: str,
    language: str,
    page_image_paths: list[str],
    output_dir: Path,
) -> tuple[list[PageResult], list[dict]]:
    """Extract all pages of a document with safe resume."""
    output_dir.mkdir(parents=True, exist_ok=True)
    extractions_dir = output_dir / "extractions" / doc_id
    extractions_dir.mkdir(parents=True, exist_ok=True)

    successful: list[PageResult] = []
    failed: list[dict] = []

    for page_num, image_path in enumerate(page_image_paths, start=1):
        output_path = extractions_dir / f"page_{page_num:03d}.json"

        if output_path.exists():
            log.info(f"  [SKIP] {doc_id} p{page_num:03d} — already extracted")
            # Load existing result for returning to caller
            with open(output_path, "r", encoding="utf-8") as f:
                successful.append(PageResult.model_validate_json(f.read()))
            continue

        try:
            log.info(f"  [RUN]  {doc_id} p{page_num:03d}...")
            page_result = extract_page(
                doc_id=doc_id,
                doc_name=doc_name,
                doc_type=doc_type,
                page_num=page_num,
                image_path=image_path,
                language=language,
            )

            # Save to disk immediately
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(page_result.model_dump_json(indent=2))

            successful.append(page_result)

        except Exception as e:
            log.error(f"  [FAIL] {doc_id} p{page_num:03d}: {e}")
            failed.append({"doc_id": doc_id, "page_num": page_num, "error": str(e)})
            # Ensure cleanup on failure
            torch.cuda.empty_cache()
            gc.collect()

    return successful, failed
