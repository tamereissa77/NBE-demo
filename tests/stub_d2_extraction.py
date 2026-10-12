"""Stand-in for the D2 extraction service, for testing the intake path on a machine with no free GPU.

Same API as services/d2_extraction (POST /v1/extract multipart, GET /v1/jobs/{id}, GET /v1/jobs/{id}/result,
GET /health, optional EXTRACTION_TOKEN). Instead of running the OCR model it replays an extraction
nbe-working already produced: the result zip holds that document's page JSON and crops, read from a mounted
nbe-working checkout, in the layout the real service returns.

A document id that nbe-working never extracted is replayed from STUB_FALLBACK (default legal-circular_4)
with the ids rewritten, so that "a new document" can be tested too.

It shares nothing with D2 but the network, like the real service on the GB10:

    docker run --rm -d --name nbe-d2-extract --network nbe-core \
      -v ~/projects/nbe-working:/src:ro -v "$(pwd)/tests:/tests:ro" \
      nbe-d2:latest uvicorn --app-dir /tests stub_d2_extraction:app --host 0.0.0.0 --port 8000
"""
import io
import json
import os
import uuid
import zipfile
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response

SRC = Path(os.environ.get("STUB_SOURCE", "/src"))
ROOTS = ("pipeline_output", "data/legacy/pipeline_output")
FALLBACK = os.environ.get("STUB_FALLBACK", "legal-circular_4")
TOKEN = os.environ.get("EXTRACTION_TOKEN", "")
app = FastAPI(title="stub D2 extraction")
_jobs: dict[str, dict] = {}
_results: dict[str, bytes] = {}


def authorised(authorization: str = Header("")) -> None:
    if TOKEN and authorization != f"Bearer {TOKEN}":
        raise HTTPException(401, "missing or wrong token")


def find(doc_id: str) -> tuple[Path, str] | None:
    for root in ROOTS:
        for name in (doc_id, doc_id.replace("-", "_"), doc_id.replace("_", "-", 1)):
            if (SRC / root / "extractions" / name).is_dir():
                return SRC / root, name
    return None


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": True, "stub": True}


@app.post("/v1/extract", status_code=202, dependencies=[Depends(authorised)])
async def extract(file: UploadFile = File(...), doc_id: str = Form(...), doc_name: str = Form(""),
                  doc_type: str = Form("SOP"), language: str = Form("ara")):
    if not (await file.read()).startswith(b"%PDF"):
        raise HTTPException(400, "the file is not a PDF")
    root, src_id = find(doc_id) or find(FALLBACK)
    buf, n = io.BytesIO(), 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for f in sorted((root / "extractions" / src_id).glob("page_*.json")):
            page = json.loads(f.read_text(encoding="utf-8").replace(src_id, doc_id))      # ids and crop paths carry the document id
            page["doc_name"] = doc_name
            for b in page["blocks"]:
                if b.get("crop_path"):
                    z.write(root / b["crop_path"].replace(doc_id, src_id), b["crop_path"])
            z.writestr(f"extractions/{doc_id}/{f.name}", json.dumps(page, ensure_ascii=False, indent=2))
            n += 1
    job_id = str(uuid.uuid4())
    _results[job_id] = buf.getvalue()
    _jobs[job_id] = {"job_id": job_id, "status": "complete", "doc_id": doc_id, "doc_name": doc_name, "total_pages": n,
                     "pages_done": n, "failed_pages": [], "error": None}
    return {**_jobs[job_id], "status": "accepted"}


@app.get("/v1/jobs/{job_id}", dependencies=[Depends(authorised)])
def job(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(404, "unknown job")
    return _jobs[job_id]


@app.get("/v1/jobs/{job_id}/result", dependencies=[Depends(authorised)])
def result(job_id: str):
    if job_id not in _results:
        raise HTTPException(404, "unknown job")
    return Response(_results[job_id], media_type="application/zip")
