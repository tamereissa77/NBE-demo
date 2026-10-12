"""PDF to page images, as nbe-working's orchestrator did before calling the extraction service."""
from pathlib import Path

import pypdfium2 as pdfium

from app.config import settings


def render_pdf(pdf_path: Path, images_dir: Path) -> list[str]:
    """Write page_001.png ... into images_dir and return their paths in page order."""
    images_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(pdf_path))
    paths = []
    for i in range(len(pdf)):
        path = images_dir / f"page_{i + 1:03d}.png"
        pdf[i].render(scale=settings.render_scale).to_pil().save(path)
        paths.append(str(path))
    return paths
