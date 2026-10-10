"""PDF uploads. The first page is rendered to an image for the reader, and the file's own record of how it
was made is checked: which program wrote it, whether it was changed after it was created, and whether it was
saved again on top of an earlier version. These are facts about the file, not proof of anything: a scanner
app and an image editor both leave their name, and an officer decides what it means.
"""
import io
import re
from datetime import datetime

import pypdfium2 as pdfium
from pypdf import PdfReader

# Programs that edit pages rather than only produce them. "lens" and "editor" match the image check's list.
EDITORS = ("photoshop", "illustrator", "gimp", "inkscape", "canva", "pixlr", "coreldraw", "lens", "editor", "ilovepdf", "sejda",
           "pdfescape", "smallpdf", "pdf-xchange", "phantompdf", "pdfelement", "nitro pro", "acrobat pro", "libreoffice draw")
RENDER_LONG_SIDE = 2000          # pixels: about 170 dpi for an A4 page, more than the reader uses


def is_pdf(content: bytes) -> bool:
    return b"%PDF-" in content[:1024]


def render(content: bytes) -> tuple[bytes, int]:
    """(PNG of the first page, number of pages)."""
    pdf = pdfium.PdfDocument(content)
    page = pdf[0]
    image = page.render(scale=RENDER_LONG_SIDE / max(page.get_size())).to_pil().convert("RGB")
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue(), len(pdf)


def _when(value) -> datetime | None:
    """PDF dates are D:YYYYMMDDHHmmSS plus a time zone; the zone is ignored (both dates of a file share it)."""
    m = re.search(r"(\d{14})", str(value or ""))
    try:
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S") if m else None
    except ValueError:
        return None


def inspect(content: bytes) -> dict:
    """What the file says about itself, and `findings`: pdf_editor, pdf_modified, pdf_revisions."""
    out = {"kind": "pdf", "producer": None, "creator": None, "created": None, "modified": None, "editor": None, "findings": []}
    # Every save appended to an existing file ends with its own %%EOF. A "linearized" (web-optimised) file has
    # two from the start, which is not a second save.
    out["revisions"] = max(1, content.count(b"%%EOF") - (1 if b"/Linearized" in content[:2048] else 0))
    try:
        meta = PdfReader(io.BytesIO(content)).metadata or {}
    except Exception:  # noqa: BLE001 - a file whose record cannot be read is still rendered and read
        meta = {}
    out["producer"], out["creator"] = (str(meta.get(k) or "").strip() or None for k in ("/Producer", "/Creator"))
    created, modified = _when(meta.get("/CreationDate")), _when(meta.get("/ModDate"))
    out["created"], out["modified"] = (d.isoformat(sep=" ") if d else None for d in (created, modified))
    tools = f"{out['producer'] or ''} {out['creator'] or ''}".lower()
    out["editor"] = next((e for e in EDITORS if e in tools), None)
    if out["editor"]:
        out["findings"].append("pdf_editor")
    if created and modified and (modified - created).total_seconds() > 120:
        out["findings"].append("pdf_modified")
    if out["revisions"] > 1:
        out["findings"].append("pdf_revisions")
    return out
