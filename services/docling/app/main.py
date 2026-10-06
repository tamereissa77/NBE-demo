"""Document conversion for D2/D5/D6 (Docling, CPU): PDF/DOCX/PPTX/HTML -> Markdown + page-aware sections.

POST /convert multipart `file` -> {markdown, pages, sections: [{heading, text, page}], arabic_ratio, rtl_pdf, latency_ms}
POST /render  multipart `file` (PDF), dpi? -> {pages: [png_base64, ...]}

Measured on GB10 (Phase 1): Docling is exact on source formats (DOCX/HTML/MD), but on PDFs it
reads the Arabic text layer in visual order (reversed digits, scrambled line wraps and table
cells). So for PDFs whose text is mostly Arabic (`rtl_pdf: true`), demo services render pages
with /render and transcribe them with the vision LLM instead. OCR is off here for the same reason.
"""
import base64
import io
import os
import re
import tempfile
import time

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
import pypdfium2 as pdfium
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

opts = PdfPipelineOptions(do_ocr=False, do_table_structure=True)
converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
app = FastAPI(title="NBE Docling")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/convert")
async def convert(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename or "")[1].lower() or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp.flush()
        t = time.time()
        try:
            doc = converter.convert(tmp.name).document
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(422, f"conversion failed: {type(exc).__name__}: {exc}") from exc

    sections, current = [], {"heading": None, "text": [], "page": None}
    for item, _level in doc.iterate_items():
        page = item.prov[0].page_no if getattr(item, "prov", None) else None
        label = str(getattr(item, "label", ""))
        text = getattr(item, "text", "") or ""
        if "header" in label or label.endswith("title"):
            if current["text"] or current["heading"]:
                sections.append({**current, "text": "\n".join(current["text"])})
            current = {"heading": text, "text": [], "page": page}
        elif text:
            current["text"].append(text)
            current["page"] = current["page"] or page
    if current["text"] or current["heading"]:
        sections.append({**current, "text": "\n".join(current["text"])})

    markdown = doc.export_to_markdown()
    letters = re.findall(r"[A-Za-z\u0600-\u06FF]", markdown)
    arabic_ratio = round(sum("\u0600" <= c <= "\u06FF" for c in letters) / max(len(letters), 1), 2)
    return {"markdown": markdown, "pages": doc.num_pages(), "sections": sections, "arabic_ratio": arabic_ratio,
            "rtl_pdf": suffix == ".pdf" and arabic_ratio > 0.3, "latency_ms": int((time.time() - t) * 1000)}


@app.post("/render")
async def render(file: UploadFile = File(...), dpi: int = Form(150)):
    """PDF pages -> PNG images for vision-LLM transcription (Arabic PDFs)."""
    pdf = pdfium.PdfDocument(await file.read())
    pages = []
    for page in pdf:
        img = page.render(scale=dpi / 72).to_pil()
        buf = io.BytesIO()
        img.save(buf, "PNG")
        pages.append(base64.b64encode(buf.getvalue()).decode())
    return {"pages": pages, "dpi": dpi}
