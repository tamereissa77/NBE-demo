"""D2 extraction service: nbe-working's extraction service, for new scanned documents in D2.

    GET  /health                    service and model state
    POST /v1/extract                submit a PDF (multipart); background job, one at a time on the GPU
    GET  /v1/jobs/{job_id}          job status
    GET  /v1/jobs/{job_id}/result   when complete: a zip of the page JSON and the crop images

extractor.py, cropper.py, coords.py and schemas.py are nbe-working's files (extraction_service and
nbe_schemas), with imports renamed and the model read from a local folder. What differs here:
  - the PDF arrives in the request and the result leaves in a response, so the service can run on another
    machine than D2 (the GB10 holds the GPU and the model; D2 may run on a workstation). nbe-working
    passed file paths on a volume both services mounted;
  - rendering the PDF to page images (the orchestrator's step) happens in this service;
  - nothing is forwarded to an indexing service: D2 fetches the result and builds its own passages;
  - a new submission of a document clears its earlier output first, so a replaced PDF is read again.
The files it writes, and the zip it returns, keep nbe-working's layout:
    extractions/<doc_id>/page_NNN.json    crops/<doc_id>/page_NNN/<block>.png

Back-office only: started on demand, not part of the running demo. Set EXTRACTION_TOKEN to require
`Authorization: Bearer <token>` when the port is reachable from other machines.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

import torch
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import settings
from app.cropper import generate_crops_for_document
from app.extractor import extract_document, is_model_loaded, load_model
from app.render import render_pdf

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
DOC_ID = r"^[A-Za-z0-9_\-]{1,80}$"
TOKEN = os.environ.get("EXTRACTION_TOKEN", "")


class Job(BaseModel):
    job_id: str
    status: str                      # accepted | running | complete | failed
    doc_id: str
    doc_name: str = ""
    doc_type: str = "SOP"
    language: str = "ara"
    total_pages: int = 0
    pages_done: int = 0
    failed_pages: list[dict] = []
    error: str | None = None


_jobs: dict[str, Job] = {}
_gpu = threading.Lock()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        load_model()
    except Exception as exc:                       # stay up so /health can report it
        log.error(f"Model failed to load: {exc}")
    yield


app = FastAPI(title="NBE D2 extraction service", lifespan=lifespan)


def authorised(authorization: str = Header("")) -> None:
    if TOKEN and authorization != f"Bearer {TOKEN}":
        raise HTTPException(401, "missing or wrong token")


def _run(job_id: str, pdf: Path) -> None:
    """Runs in the thread pool, one job at a time (one GPU)."""
    with _gpu:
        _extract(_jobs[job_id], pdf)


def _extract(job: Job, pdf: Path) -> None:
    job.status = "running"
    data, output_dir = Path(settings.data_dir), Path(settings.output_dir)
    try:
        for stale in (output_dir / "extractions" / job.doc_id, output_dir / "crops" / job.doc_id, data / "docs_images" / job.doc_id):
            shutil.rmtree(stale, ignore_errors=True)
        images = render_pdf(pdf, data / "docs_images" / job.doc_id)
        job.total_pages = len(images)
        pages, failed = extract_document(doc_id=job.doc_id, doc_name=job.doc_name, doc_type=job.doc_type,
                                         language=job.language, page_image_paths=images, output_dir=output_dir)
        if pages:
            pages = generate_crops_for_document(pages, str(Path(images[0]).parent), output_dir)
            for page in pages:                      # again, now with crop_path filled in
                out = output_dir / "extractions" / job.doc_id / f"page_{page.page_num:03d}.json"
                out.write_text(json.dumps(page.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
        job.pages_done, job.failed_pages = len(pages), failed
        job.status = "complete"
        log.info(f"[{job.job_id}] {job.doc_id}: {len(pages)} pages extracted, {len(failed)} failed")
    except Exception as exc:
        log.error(f"[{job.job_id}] failed: {exc}", exc_info=True)
        job.status, job.error = "failed", str(exc)


@app.get("/health")
def health() -> dict:
    gpu = torch.cuda.is_available()
    return {"status": "ok" if is_model_loaded() else "degraded", "model_loaded": is_model_loaded(), "gpu_available": gpu,
            "gpu_name": torch.cuda.get_device_name(0) if gpu else None,
            "vram_free_gb": round(torch.cuda.mem_get_info()[0] / 1e9, 2) if gpu else None}


@app.post("/v1/extract", response_model=Job, status_code=202, dependencies=[Depends(authorised)])
async def submit(background: BackgroundTasks, file: UploadFile = File(...), doc_id: str = Form(..., pattern=DOC_ID),
                 doc_name: str = Form(""), doc_type: str = Form("SOP"), language: str = Form("ara")) -> Job:
    if not is_model_loaded():
        raise HTTPException(503, "The model is not loaded.")
    data = await file.read()
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "the file is not a PDF")
    pdf = Path(settings.data_dir) / "incoming" / f"{doc_id}.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(data)
    job = Job(job_id=str(uuid.uuid4()), status="accepted", doc_id=doc_id, doc_name=doc_name or f"{doc_id}.pdf",
              doc_type=doc_type, language=language)
    _jobs[job.job_id] = job
    background.add_task(_run, job.job_id, pdf)
    return job


@app.get("/v1/jobs/{job_id}", response_model=Job, dependencies=[Depends(authorised)])
def job_status(job_id: str) -> Job:
    if job_id not in _jobs:
        raise HTTPException(404, "unknown job")
    return _jobs[job_id]


@app.get("/v1/jobs/{job_id}/result", dependencies=[Depends(authorised)])
def result(job_id: str) -> FileResponse:
    """The document's page JSON and crops as one zip, in nbe-working's layout."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")
    if job.status != "complete":
        raise HTTPException(409, f"job is {job.status}")
    output_dir = Path(settings.output_dir)
    archive = Path(settings.data_dir) / "results" / f"{job_id}.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as z:      # PNG crops are already compressed
        for sub in ("extractions", "crops"):
            for f in sorted((output_dir / sub / job.doc_id).rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(output_dir).as_posix())
    return FileResponse(archive, media_type="application/zip", filename=f"{job.doc_id}.zip")
