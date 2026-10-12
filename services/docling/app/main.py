"""Document conversion for D2/D5/D6 (Docling, CPU): PDF/DOCX/PPTX/HTML -> Markdown + page-aware sections.

POST /convert multipart `file` -> {markdown, pages, sections: [{heading, text, page}], arabic_ratio, rtl_pdf,
                                   page_text: [{page, text, arabic_ratio}], page_markdown: [{page, markdown}], latency_ms}
POST /render  multipart `file` (PDF), dpi?, pages? ("1,3") -> {pages: [png_base64, ...], page_numbers}

`page_text` is the raw text layer of each PDF page. A scanned page has none, so callers can decide page
by page which ones need the vision model, instead of treating the file as all typed or all scanned.
`page_markdown` is the converted document one page at a time (headings, tables), for callers that cite pages.
Unlike `markdown` it keeps page headers and footers: letters and circulars carry their date and reference there.

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
from docling_core.types.doc import ContentLayer
import pypdfium2 as pdfium
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

opts = PdfPipelineOptions(do_ocr=False, do_table_structure=True)
converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
app = FastAPI(title="NBE Docling")


@app.get("/health")
def health():
    return {"status": "ok"}


def _arabic_ratio(text: str) -> float:
    letters = re.findall(r"[A-Za-z\u0600-\u06FF]", text)
    return round(sum("\u0600" <= c <= "\u06FF" for c in letters) / max(len(letters), 1), 2)


def _page_text(data: bytes) -> list[dict]:
    out = []
    for n, page in enumerate(pdfium.PdfDocument(data), start=1):
        text = page.get_textpage().get_text_range()
        out.append({"page": n, "text": text, "arabic_ratio": _arabic_ratio(text)})
    return out


@app.post("/convert")
async def convert(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename or "")[1].lower() or ".pdf"
    data = await file.read()
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(data)
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
    page_markdown = [{"page": n, "markdown": doc.export_to_markdown(
        page_no=n, included_content_layers={ContentLayer.BODY, ContentLayer.FURNITURE}, escape_html=False, compact_tables=True)}
        for n in range(1, doc.num_pages() + 1)]
    arabic_ratio = _arabic_ratio(markdown)
    return {"markdown": markdown, "pages": doc.num_pages(), "sections": sections, "arabic_ratio": arabic_ratio,
            "rtl_pdf": suffix == ".pdf" and arabic_ratio > 0.3, "page_text": _page_text(data) if suffix == ".pdf" else [],
            "page_markdown": page_markdown,
            "latency_ms": int((time.time() - t) * 1000)}


@app.post("/render")
async def render(file: UploadFile = File(...), dpi: int = Form(150), pages: str = Form("")):
    """PDF pages -> PNG images for vision-LLM transcription (Arabic and scanned pages). `pages` limits it to some pages."""
    pdf = pdfium.PdfDocument(await file.read())
    wanted = [int(n) for n in pages.split(",") if n.strip().isdigit() and 1 <= int(n) <= len(pdf)] or list(range(1, len(pdf) + 1))
    out = []
    for n in wanted:
        img = pdf[n - 1].render(scale=dpi / 72).to_pil()
        buf = io.BytesIO()
        img.save(buf, "PNG")
        out.append(base64.b64encode(buf.getvalue()).decode())
    return {"pages": out, "page_numbers": wanted, "dpi": dpi}
