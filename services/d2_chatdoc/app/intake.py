"""Back-office intake of a new scanned document into D2, without re-ingesting anything else.

    POST   /upload              a PDF with its titles, type and roles (manager only)
    GET    /upload/jobs[/{id}]  progress of an intake
    GET    /upload/documents    the documents added this way
    DELETE /upload/{doc_id}     remove one of them

What happens to an uploaded PDF:
  1. it is saved on the uploads volume and sent to the extraction service (services/d2_extraction:
     nbe-working's Chandra OCR service, on this machine or on the GB10), which renders the pages, reads
     them into typed blocks and cuts one crop per block; the result comes back as a zip in
     nbe-working's output layout;
  2. that output is normalised into the layout of data/seed/d2/circulars, by the same rules as
     tools/import_nbe_working.py, under <uploads>/circulars;
  3. main.py builds the passages with app/scans.py and adds only this document's passages to the
     existing collection. No other document is embedded again and no collection is rebuilt.

This replaces what MinIO did in nbe-working: the bucket and its webhook become POST /upload, and the
crops are served from the volume by the existing /crop endpoint.

Switched on by the uploads volume and D2_EXTRACTION_URL (docker-compose.d2-extract.yml). Without them
the endpoints answer 404 and D2 is unchanged.
"""
import asyncio
import io
import json
import os
import re
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app import scans

UPLOADS = Path(os.environ.get("D2_UPLOADS_DIR", "/uploads"))
EXTRACTION_URL = os.environ.get("D2_EXTRACTION_URL", "").rstrip("/")
EXTRACTION_TOKEN = os.environ.get("D2_EXTRACTION_TOKEN", "")
CORPUS = UPLOADS / "circulars"              # same layout as data/seed/d2/circulars, read by scans.load
RAW = UPLOADS / "pipeline_output"           # the extraction service's result, unpacked, in nbe-working's layout
UPLOAD_ROLE = "manager"
DOC_TYPES = ("legal_circular", "sop")
FILE_NAME = re.compile(r"^[A-Za-z0-9_\- ]{1,80}\.pdf$", re.I)
POLL_S, TIMEOUT_S = 5, 4 * 3600

_jobs: dict[str, dict] = {}
_one_at_a_time = asyncio.Lock()


def enabled() -> bool:
    return bool(EXTRACTION_URL) and UPLOADS.is_dir()


def norm(name: str) -> str:
    return name.replace("-", "_")


def manifest() -> list[dict]:
    f = CORPUS / "manifest.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def _write_manifest(entries: list[dict]) -> None:
    CORPUS.mkdir(parents=True, exist_ok=True)
    (CORPUS / "manifest.json").write_text(json.dumps(sorted(entries, key=lambda e: e["doc_id"]), ensure_ascii=False, indent=1) + "\n",
                                          encoding="utf-8")


def normalise(raw_root: Path, raw_id: str, out_root: Path, entry: dict) -> dict:
    """One document from nbe-working's output layout into D2's corpus layout. Returns its manifest entry.

    Same result as tools/import_nbe_working.py for that document: ids with underscores, the block fields
    D2 uses, crops copied beside the page JSON, no machine-specific page image path.
    """
    doc_id = norm(raw_id)
    for sub in ("extractions", "crops"):
        shutil.rmtree(out_root / sub / doc_id, ignore_errors=True)
    pages = sorted((raw_root / "extractions" / raw_id).glob("page_*.json"))
    if not pages:
        raise RuntimeError(f"the extraction produced no pages for {raw_id}")
    n_blocks, source_name = 0, ""
    for f in pages:
        page = json.loads(f.read_text(encoding="utf-8"))
        page_num, blocks = int(f.stem.split("_")[1]), []
        for b in page["blocks"]:
            crop_rel = None
            if b.get("crop_path"):                     # a block without a usable bounding box has no crop
                crop_src = raw_root / b["crop_path"]
                crop_rel = Path("crops") / doc_id / f"page_{page_num:03d}" / norm(crop_src.name)
                (out_root / crop_rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(crop_src, out_root / crop_rel)
            blocks.append({"block_id": norm(b["block_id"]), "block_type": b["block_type"], "text": b.get("text") or "",
                           "table_data": b.get("table_data"), "bbox": b.get("bbox"), "crop_path": crop_rel and crop_rel.as_posix()})
        out = out_root / "extractions" / doc_id / f"page_{page_num:03d}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"doc_id": doc_id, "page_num": page_num, "original_size": page.get("original_size"),
                                   "inference_size": page.get("inference_size", page.get("original_size")),
                                   "blocks": blocks}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        n_blocks += len(blocks)
        source_name = page.get("doc_name", "")
    return {"doc_id": doc_id, "source_name": source_name, **entry, "lang": "ar", "pages": len(pages), "blocks": n_blocks}


async def _extract(job: dict, pdf: Path) -> None:
    """Send the PDF to the extraction service, wait as nbe-working's orchestrator did, then fetch its output.

    The file goes in the request and the page JSON and crops come back as a zip, so the service can be on
    another machine (the GB10) than D2. The zip is unpacked under RAW, in nbe-working's layout."""
    headers = {"Authorization": f"Bearer {EXTRACTION_TOKEN}"} if EXTRACTION_TOKEN else {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10), headers=headers) as client:
        r = await client.post(f"{EXTRACTION_URL}/v1/extract", files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")},
                              data={"doc_id": job["raw_id"], "doc_name": pdf.name, "doc_type": job["entry"]["type"], "language": "ara"})
        if r.status_code != 202:
            raise RuntimeError(f"extraction service refused the document: {r.status_code} {r.text[:300]}")
        ext_id, waited = r.json()["job_id"], 0
        while True:
            status = (await client.get(f"{EXTRACTION_URL}/v1/jobs/{ext_id}")).json()
            job["pages"] = status.get("total_pages") or job.get("pages")
            if status["status"] == "complete":
                # A document with unread pages is not indexed: a partial circular would answer wrongly without saying so
                if status.get("failed_pages"):
                    raise RuntimeError(f"pages not read: {[p['page_num'] for p in status['failed_pages']]}")
                break
            if status["status"] == "failed":
                raise RuntimeError(f"extraction failed: {status.get('error')}")
            if waited >= TIMEOUT_S:
                raise RuntimeError("extraction timed out")
            await asyncio.sleep(POLL_S)
            waited += POLL_S
        r = await client.get(f"{EXTRACTION_URL}/v1/jobs/{ext_id}/result")
        r.raise_for_status()
    _unpack(r.content, job["raw_id"])


def _unpack(archive: bytes, raw_id: str) -> None:
    """Unpack one document's result under RAW. Only extractions/<id>/... and crops/<id>/... are accepted."""
    for sub in ("extractions", "crops"):
        shutil.rmtree(RAW / sub / raw_id, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        for name in z.namelist():
            parts = Path(name).parts
            if len(parts) < 3 or parts[0] not in ("extractions", "crops") or parts[1] != raw_id or ".." in parts:
                raise RuntimeError(f"unexpected file in the extraction result: {name}")
            out = RAW.joinpath(*parts)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(name))


def build_router(index_doc) -> APIRouter:
    """`index_doc(doc_id)` is main.py's: reload the corpus, replace this document's passages in the collection."""
    router = APIRouter()

    def gate(role: str) -> None:
        if not enabled():
            raise HTTPException(404, "document intake is not installed (docker-compose.d2-extract.yml)")
        if role != UPLOAD_ROLE:
            raise HTTPException(403, "only a manager may add or remove documents")

    async def run(job: dict, pdf: Path) -> None:
        def stage(s: str) -> None:
            job.update(status=s, updated_at=datetime.now(timezone.utc).isoformat())
        async with _one_at_a_time:
            try:
                stage("extracting")
                await _extract(job, pdf)
                stage("indexing")
                entry = normalise(RAW, job["raw_id"], CORPUS, job["entry"])
                _write_manifest([e for e in manifest() if e["doc_id"] != entry["doc_id"]] + [entry])
                job.update(pages=entry["pages"], blocks=entry["blocks"], passages=await index_doc(entry["doc_id"]))
                stage("complete")
            except httpx.TransportError as exc:
                job["error"] = f"the extraction service is not reachable at {EXTRACTION_URL} (start nbe-d2-extract): {exc}"
                stage("failed")
            except Exception as exc:                   # the job carries the reason; nothing half-done is indexed
                job["error"] = str(exc)
                stage("failed")

    @router.post("/upload", status_code=202)
    async def upload(file: UploadFile = File(...), role: str = Form(...), title_ar: str = Form(...), title_en: str = Form(...),
                     doc_type: str = Form("legal_circular"), roles: str = Form("legal_counsel,manager")):
        gate(role)
        name = Path(file.filename or "").name
        if not FILE_NAME.match(name):
            raise HTTPException(400, "file name must be letters, digits, spaces, - or _ and end in .pdf")
        allowed = [r.strip() for r in roles.split(",") if r.strip()]
        if doc_type not in DOC_TYPES or not allowed or set(allowed) - scans.ROLE_IDS:
            raise HTTPException(400, f"doc_type must be one of {DOC_TYPES}; roles must come from {sorted(scans.ROLE_IDS)}")
        data = await file.read()
        if not data.startswith(b"%PDF"):
            raise HTTPException(400, "the file is not a PDF")
        raw_id = name[:-4].replace(" ", "_")           # as nbe-working's orchestrator derived the document id
        pdf = UPLOADS / "incoming" / f"{raw_id}.pdf"
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(data)
        job = {"job_id": str(uuid.uuid4()), "doc_id": norm(raw_id), "raw_id": raw_id, "status": "accepted",
               # the manager can always read what the manager added
               "entry": {"type": doc_type, "roles": list(dict.fromkeys(allowed + [UPLOAD_ROLE])), "title_ar": title_ar.strip(), "title_en": title_en.strip()},
               "updated_at": datetime.now(timezone.utc).isoformat()}
        _jobs[job["job_id"]] = job
        job["task"] = asyncio.create_task(run(job, pdf))
        return public(job)

    def public(job: dict) -> dict:
        return {k: v for k, v in job.items() if k not in ("task", "raw_id")}

    @router.get("/upload/jobs")
    def jobs(role: str):
        gate(role)
        return [public(j) for j in _jobs.values()]

    @router.get("/upload/jobs/{job_id}")
    def job_status(job_id: str, role: str):
        gate(role)
        if job_id not in _jobs:
            raise HTTPException(404, "unknown job")
        return public(_jobs[job_id])

    @router.get("/upload/documents")
    def documents(role: str):
        gate(role)
        return manifest()

    @router.delete("/upload/{doc_id}")
    async def remove(doc_id: str, role: str):
        gate(role)
        entries = manifest()
        if doc_id not in {e["doc_id"] for e in entries}:
            raise HTTPException(404, "not an uploaded document")
        async with _one_at_a_time:
            _write_manifest([e for e in entries if e["doc_id"] != doc_id])
            for sub in ("extractions", "crops"):
                shutil.rmtree(CORPUS / sub / doc_id, ignore_errors=True)
            for pdf in (UPLOADS / "incoming").glob("*.pdf"):
                if norm(pdf.stem) == doc_id:
                    pdf.unlink(missing_ok=True)
            for raw in [d for sub in ("extractions", "crops") for d in (RAW / sub).glob("*") if norm(d.name) == doc_id]:
                shutil.rmtree(raw, ignore_errors=True)
            # If a seed document has the same id, its passages come back; otherwise the document is gone
            return {"removed": doc_id, "passages_now": await index_doc(doc_id)}

    return router
